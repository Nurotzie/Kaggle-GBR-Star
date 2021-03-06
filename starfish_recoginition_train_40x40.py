# -*- coding: utf-8 -*-

#Upload API key
from google.colab import files
files.upload()

#Create API key folder/file
!mkdir ~/.kaggle
!cp /content/kaggle.json ~/.kaggle/
!chmod 600 ~/.kaggle/kaggle.json
!pip install --upgrade --force-reinstall --no-deps kaggle

#Download the Dataz
!kaggle competitions download -c tensorflow-great-barrier-reef

#Unzip the Dataz
!unzip -q tensorflow-great-barrier-reef.zip

!pip install -U --pre tensorflow=="2.7.0"
!pip install keras-tuner --upgrade

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
import pathlib
import cv2
import json
import random

import keras_tuner as kt
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
from tensorflow.keras import backend
from tensorflow.keras.utils import image_dataset_from_directory
from tensorflow.keras.preprocessing import image

import numpy as np
import pandas as pd
from PIL import ImageFile
from PIL import Image
from six import BytesIO
import matplotlib.pyplot as plt

#Colab only
#from google.colab import files

#Consts
Max_Anno_Width = 160
Min_Anno_Width = 20

Max_Anno_Height = 120
Min_Anno_Height = 16

Image_Width = 1280
Image_Height = 720

Scale_Multiplier = 16

#Crop Size
C_Height = 40
C_Width = 40

#Configs
#Folder Info
download_base = "train.csv"
video_base = "train_images/"
video_to_base = f"parsed_data_{C_Height}x_{C_Width}"
Save_Path = f"Resnet50_{C_Height}x_{C_Width}_Manual_Save"
Batch_Size = 16

#Read in annotation data
annotation_data = pd.read_csv(download_base)

#Unused, if needed for later
def get_img_array(img_path, target_size):
  """Convert an image to an array"""
  img = image.load_img(img_path, target_size=target_size) #keras.utils.load_img(img_path, target_size=target_size)
  array = image.img_to_array(img)
  array = np.expand_dims(array, axis=0)
  return array


#Utils
def create_and_overwrite_folder(path):
  if os.path.exists(path):
    shutil.rmtree(path)
  
  os.mkdir(path)
  

def crop_to_size_around_starfish(old_xywh, old_img, crop_height=C_Height, crop_width=C_Width, max_height=Image_Height, max_width=Image_Width):
  #greedy crop to gt box
  (mid_x, mid_y,) = (old_xywh["x"]+old_xywh["width"]/2, old_xywh["y"]+old_xywh["height"]/2)
  (left, top, right, bottom) = (mid_x-crop_width/2, mid_y-crop_height/2, mid_x+crop_width/2, mid_y+crop_height/2)
  #new annotations
  new_annotations = {"x":crop_width/2-old_xywh["width"]/2, "y":crop_height/2-old_xywh["height"]/2, "width":old_xywh["width"], "height":old_xywh["height"]}

  #check out of bounds
  if left < 0:
    diff = -left
    (left, top, right, bottom) = (0, top, right+diff, bottom)
    new_annotations["x"] -= diff
  if right > max_width:
    diff = right - max_width
    (left, top, right, bottom) = (max_width-crop_width-diff, top, max_width, bottom)
    new_annotations["x"] += diff  
  if top < 0:
    diff = -top
    (left, top, right, bottom) = (left, 0, right, bottom+diff)
    new_annotations["y"] -= diff
  if bottom > max_height:
    diff = bottom - max_height
    (left, top, right, bottom) = (left, max_height-crop_height-diff, right, max_height)
    new_annotations["y"] += diff
  new_img = old_img.crop((left, top, right, bottom))

  return new_img, new_annotations


def load_anno_set(set_id):
  """Load in annotation data from a folder with the set_id"""
  anno_data = annotation_data.loc[annotation_data['video_id'] == set_id]

  anno_data_no_star = anno_data.loc[anno_data["annotations"] == "[]"]
  anno_data_no_star_names = anno_data_no_star["video_frame"]

  anno_data_star = anno_data.loc[anno_data["annotations"] != "[]"]
  anno_data_star_names = anno_data_star["video_frame"]

  return anno_data_no_star_names , anno_data_star_names


def make_subset2(subset_name, start_index, end_index):
  """Generate a subet of data as a file structure"""  
  sub_path = pathlib.Path(video_to_base+"/")
  for category in ("no_star", "star"):
    dir = sub_path / subset_name / category
    os.makedirs(dir)
    fnames = [f"{category}.{i}.jpg" for i in range(start_index, end_index)]

    for fname in fnames:
      shutil.copyfile(src=sub_path / fname, dst=dir / fname)

def random_xywh_coord():
  """Create a random xywh coord excluding area covered by input anno_coord"""
  
  rand_y = random.randint(Max_Anno_Height, (Image_Height - Max_Anno_Height))
  rand_x = random.randint(Max_Anno_Width, (Image_Height - Max_Anno_Width))
  rand_w = random.randint(Min_Anno_Width,Max_Anno_Width)
  rand_h = random.randint(Min_Anno_Height,Max_Anno_Height)
  return {"x": rand_x, "y": rand_y, "width": rand_w, "height": rand_h}

def sub_image(image_path, xywh_coords):
  """Create a new sub-image based on input coords.""" 
  size = (C_Height*Scale_Multiplier, C_Width*Scale_Multiplier)
  img_data = tf.io.gfile.GFile(image_path, 'rb').read()
  image = Image.open(BytesIO(img_data))
  new_image, new_annotations = crop_to_size_around_starfish(xywh_coords, image, crop_height=C_Height/4, crop_width=C_Width/4)
  new_image = keras.utils.img_to_array(new_image)
  new_image = tf.keras.preprocessing.image.smart_resize(new_image, size, interpolation='bilinear')
  new_image = keras.utils.array_to_img(new_image)
  return new_image

def annonation_str_to_coords(anno_str):
    """Convert string of coordinates to dict"""
    mod_anno_str = anno_str.replace("'", '"')
    return json.loads(mod_anno_str)

def gen_image_path(base_path, image_key):
    """generates the image path based of a key provided in the format: #-## (0-60)"""
    image_key= image_key.split("-")
    folder = image_key[0]
    file = image_key[1]
       
    return f"{base_path}{folder}/{file}.jpg"

#Setup annotation data
no_star_data_set = []
star_data_set = []
for i in range(3):
  anno_data_no_star_names, anno_data_star_names = load_anno_set(i)
  no_star_data_set.append(anno_data_no_star_names.astype("float32"))
  star_data_set.append(anno_data_star_names.astype("float32"))

#Buid a dictionary of image_id : annotations
images_dict = {}
star_anno = []
no_star_anno = []
for i in annotation_data["image_id"]:
    anno = annotation_data.loc[annotation_data["image_id"] == i]
    coords = anno["annotations"]
    coords = coords.tolist()
    images_dict[i] = annonation_str_to_coords(coords[0])

#Create the Cropped images
create_and_overwrite_folder(video_to_base)

j=0
k=0
for key in images_dict.keys():
    if images_dict[key] == []:
        rand_coord = random_xywh_coord()
        path = gen_image_path(f"{video_base}video_", key)
        img = sub_image(path, rand_coord)
        img.save(f"{video_to_base}/no_star.{k}.jpg")
        k = k + 1

    for coord in images_dict[key]:
        path = gen_image_path(f"{video_base}video_", key)
        img = sub_image(path, coord)
        img.save(f"{video_to_base}/star.{j}.jpg")
        j = j+1

#Make a subset of data to run on
make_subset2("train", start_index=0, end_index=8500)
make_subset2("validation", start_index=8500, end_index=9500)
make_subset2("test", start_index=9500, end_index=11500)

#convert images to standardized floating point tensors
train_dataset = image_dataset_from_directory(
    #Select the directory
    pathlib.Path(video_to_base) / "train",
    #resize images to a standard form
    image_size = (C_Height*Scale_Multiplier,C_Width*Scale_Multiplier),
    #pack into batches
    batch_size=Batch_Size
)

validation_dataset = image_dataset_from_directory(
    pathlib.Path(video_to_base) / "validation",
    image_size = (C_Height*Scale_Multiplier,C_Width*Scale_Multiplier),
    batch_size = Batch_Size
)

test_dataset = image_dataset_from_directory(
    pathlib.Path(video_to_base) / "test",
    image_size = (C_Height*Scale_Multiplier,C_Width*Scale_Multiplier),
    batch_size = Batch_Size
)

import uuid
#Clear plot between runs
plt.clf()

#Training HyperParams
patience=5


#set callbacks
rlrp = tf.keras.callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.000001, patience=3, cooldown=2, min_delta=0.0001)
callbacks = [
    keras.callbacks.ModelCheckpoint(
        filepath=f"InceptionResNet-{C_Width}x{C_Height}-uuid-{uuid.uuid4()}.keras",
        save_best_only=False,
        monitor="val_loss"
    ),
    rlrp,
    keras.callbacks.EarlyStopping(monitor="val_loss", patience=5)
]

#HyperTuner
class HyperTuner(kt.HyperModel):
  def __init__(self, num_classes):
    self.num_classes = num_classes
    self.optimizers = {"rmsprop": tf.optimizers.RMSprop(learning_rate=1e-7, momentum=0.9), "adam": tf.keras.optimizers.Adam(learning_rate=1e-7) }

  def build(self, hp):
    filters = hp.Int(name="cnn_filters", min_value=32, max_value=2048, step=16)
    kernel_size = hp.Int(name="kernel_size", min_value=2, max_value=6, step=1)
    dropout = hp.Float(name="dropout", min_value=0.3, max_value=0.9, step=0.1)
    optimizer = hp.Choice(name="optimizer", values=["rmsprop","adam"])
    rotation = hp.Float(name="rotation_aug", min_value=0.1, max_value=0.6, step=0.1)
    zoom = hp.Float(name="zoom_aug", min_value=0.1, max_value=0.6, step=0.1)
    contrast_factor= hp.Float(name="contrast_aug", min_value=0.1, max_value=0.8, step=0.2)

    #Build Model and start Training

    #Uncomment to enable TPU ***NEEDS RAM LOADED DATAZ***
    #tpu = tf.distribute.cluster_resolver.TPUClusterResolver.connect()
    #print("Device:", tpu.master())
    #tf.keras.mixed_precision.set_global_policy("mixed_float16")



    conv_base = keras.applications.ResNet50(
        weights="imagenet",
        include_top=False,
        input_shape=(C_Height*Scale_Multiplier,C_Width*Scale_Multiplier,3)
    )

    #freeze to prevent weight updates during training
    conv_base.trainable = False

    #print(conv_base.summary())

    #set data augments
    data_augmentation = keras.Sequential(
        [
        layers.RandomTranslation(0.2, 0.2,fill_mode="reflect"),
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(rotation),
        layers.RandomZoom(zoom),
        layers.RandomContrast(contrast_factor)
        ]
    )

    #build the model including the conv base vgg16
    inputs = keras.Input(shape=(C_Height,C_Width,3))
    x = data_augmentation(inputs)
    #x = layers.Rescaling(1./255)(inputs)
    x = keras.applications.resnet.preprocess_input(x)
    x = conv_base(x)


    #Layer gen Loop, for making pyramid deep layers
    #for size in [512, 32, 64, 128, 256, 512, 256, 128, 64,32, 512]:
    for size in [filters]:
      #residual for gradient feedback
      #residual = x
      
      #Main two stack pyramid layer combo
      x = layers.Conv2D(size, kernel_size, padding="same", use_bias=False)(x)
      x = layers.BatchNormalization()(x)
      x = layers.Activation("relu")(x)
      #x = layers.MaxPooling2D(2, strides=2, padding="same")(x)
    x = layers.Dropout(dropout)(x)
      
      #Propogate the residual through the pyramid tier
      #residual = layers.Conv2D(size, 1, padding="same", use_bias=False)(residual)
      #x = layers.add([x, residual])
      #x = layers.ReLU()(x)

    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Flatten()(x)

    #Sigmoid output
    outputs = layers.Dense(2, activation="softmax")(x)
    model = keras.Model(inputs,outputs)
    model.save_weights(f'model_weights/uuid-{uuid.uuid4()}', save_format='keras', overwrite=True)
    #Build and compile
    model.compile(
        loss="sparse_categorical_crossentropy",
        optimizer=self.optimizers[optimizer],
        metrics=["accuracy"]
    )
    return model
    #Model Summary for debug
    #print(model.summary())

hypermodel = HyperTuner(num_classes=2)

tuner = kt.BayesianOptimization(
    hypermodel,
    objective="val_accuracy",
    max_trials=100,
    executions_per_trial=1,
    directory=os.path.normpath("tuner"),
    project_name='resnet50',
    overwrite=True
)
print(tuner.search_space_summary())

#Train the model
pretrained_history = tuner.search(
    train_dataset,
    epochs=100,
    validation_data=validation_dataset,
    callbacks=callbacks,
)

x = tuner.get_best_models(num_models=2)

#Test the model
test_model = keras.models.load_model("/content/resnet50-160x160.keras")
test_loss, test_acc = test_model.evaluate(test_dataset)
print(f"Test Accuracy: {test_acc: .3f}")

test_loss, test_acc = model.evaluate(test_dataset)
print(f"Test Accuracy: {test_acc: .3f}")

#Save the model
test_model.save(f'resnet50-{C_Width}x{C_Height*}x4-{test_acc}.keras')

