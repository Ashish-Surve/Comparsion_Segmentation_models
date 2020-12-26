import cv2
import keras
import numpy as np
import matplotlib.pyplot as plt

import config
import cv2
import segmentation_models as sm
#import matplotlib.pyplot as plt # remove pyplot after testing phase over
#import matplotlib.image as mpimg
import os
import albumentations as A

import glob



# important constants
#TODO:clean code later
BACKBONE = 'efficientnetb3'
CLASSES = ['car']
n_classes = 1 if len(CLASSES) == 1 else (len(CLASSES) + 1)  # case for binary and multiclass segmentation
activation = 'sigmoid' if n_classes == 1 else 'softmax'
preprocess_input = sm.get_preprocessing(BACKBONE)

# models pre load
print("Loading Models. This might take some time...")
modelUnet = sm.Unet(BACKBONE, classes=n_classes, activation=activation)
model_c = config.STYLES["unet"]
model_path = os.path.join(f"{config.MODEL_PATH}",f"{model_c}.h5")
modelUnet.load_weights(model_path)
print("Loaded Unet.")

modelFPN = sm.FPN(BACKBONE, classes=n_classes, activation=activation) 
model_c = config.STYLES["featurepyramidnetwork"]
model_path = f"{config.MODEL_PATH}{model_c}.h5"
modelFPN.load_weights(model_path)
print("Loaded FPN.")

modelLinknet = sm.Linknet(BACKBONE, classes=n_classes, activation=activation)
model_c = config.STYLES["linknet"]
model_path = f"{config.MODEL_PATH}{model_c}.h5"
modelLinknet.load_weights(model_path)
print("Loaded Linknet.")


# below was the part of the pipline is used for training and preprocessing
# TODO: Replace this pipeline with custom for faster inference.
# helper function for data visualization
def visualize(**images):
    """PLot images in one row."""
    n = len(images)
    plt.figure(figsize=(16, 5))
    for i, (name, image) in enumerate(images.items()):
        plt.subplot(1, n, i + 1)
        plt.xticks([])
        plt.yticks([])
        plt.title(' '.join(name.split('_')).title())
        plt.imshow(image)
    plt.show()
    
# helper function for data visualization    
def denormalize(x):
    """Scale image to range 0..1 for correct plot"""
    x_max = np.percentile(x, 98)
    x_min = np.percentile(x, 2)    
    x = (x - x_min) / (x_max - x_min)
    x = x.clip(0, 1)
    return x

def round_clip_0_1(x, **kwargs):
    return x.round().clip(0, 1)    

# classes for data loading and preprocessing
class Dataset:
    """CamVid Dataset. Read images, apply augmentation and preprocessing transformations.
    
    Args:
        images_dir (str): path to images folder
        masks_dir (str): path to segmentation masks folder
        class_values (list): values of classes to extract from segmentation mask
        augmentation (albumentations.Compose): data transfromation pipeline 
            (e.g. flip, scale, etc.)
        preprocessing (albumentations.Compose): data preprocessing 
            (e.g. noralization, shape manipulation, etc.)
    
    """
    
    CLASSES = ['sky', 'building', 'pole', 'road', 'pavement', 
               'tree', 'signsymbol', 'fence', 'car', 
               'pedestrian', 'bicyclist', 'unlabelled']
    
    def __init__(
            self, 
            images_dir, 
            masks_dir, 
            classes=None, 
            augmentation=None, 
            preprocessing=None,
    ):
        self.ids = os.listdir(images_dir)
        self.images_fps = [os.path.join(images_dir, image_id) for image_id in self.ids]
        self.masks_fps = [os.path.join(masks_dir, image_id) for image_id in self.ids]
        
        # convert str names to class values on masks
        self.class_values = [self.CLASSES.index(cls.lower()) for cls in classes]
        
        self.augmentation = augmentation
        self.preprocessing = preprocessing
    
    def __getitem__(self, i):
        
        # read data
        image = cv2.imread(self.images_fps[i])
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mask = cv2.imread(self.masks_fps[i], 0)
        
        # extract certain classes from mask (e.g. cars)
        masks = [(mask == v) for v in self.class_values]
        mask = np.stack(masks, axis=-1).astype('float')
        
        # add background if mask is not binary
        if mask.shape[-1] != 1:
            background = 1 - mask.sum(axis=-1, keepdims=True)
            mask = np.concatenate((mask, background), axis=-1)
        
        # apply augmentations
        if self.augmentation:
            sample = self.augmentation(image=image, mask=mask)
            image, mask = sample['image'], sample['mask']
        
        # apply preprocessing
        if self.preprocessing:
            sample = self.preprocessing(image=image, mask=mask)
            image, mask = sample['image'], sample['mask']
            
        return image, mask
        
    def __len__(self):
        return len(self.ids)
    
    
class Dataloder(keras.utils.Sequence):
    """Load data from dataset and form batches
    
    Args:
        dataset: instance of Dataset class for image loading and preprocessing.
        batch_size: Integet number of images in batch.
        shuffle: Boolean, if `True` shuffle image indexes each epoch.
    """
    
    def __init__(self, dataset, batch_size=1, shuffle=False):
        self.dataset = dataset
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.indexes = np.arange(len(dataset))

        self.on_epoch_end()

    def __getitem__(self, i):
        
        # collect batch data
        start = i * self.batch_size
        stop = (i + 1) * self.batch_size
        data = []
        for j in range(start, stop):
            data.append(self.dataset[j])
        
        # transpose list of lists
        batch = [np.stack(samples, axis=0) for samples in zip(*data)]
        
        return batch
    
    def __len__(self):
        """Denotes the number of batches per epoch"""
        return len(self.indexes) // self.batch_size
    
    def on_epoch_end(self):
        """Callback function to shuffle indexes each epoch"""
        if self.shuffle:
            self.indexes = np.random.permutation(self.indexes)  

# define heavy augmentations
def get_training_augmentation():
    train_transform = [

        A.HorizontalFlip(p=0.5),

        A.ShiftScaleRotate(scale_limit=0.5, rotate_limit=0, shift_limit=0.1, p=1, border_mode=0),

        A.PadIfNeeded(min_height=320, min_width=320, always_apply=True, border_mode=0),
        A.RandomCrop(height=320, width=320, always_apply=True),

        A.IAAAdditiveGaussianNoise(p=0.2),
        A.IAAPerspective(p=0.5),

        A.OneOf(
            [
                A.CLAHE(p=1),
                A.RandomBrightness(p=1),
                A.RandomGamma(p=1),
            ],
            p=0.9,
        ),

        A.OneOf(
            [
                A.IAASharpen(p=1),
                A.Blur(blur_limit=3, p=1),
                A.MotionBlur(blur_limit=3, p=1),
            ],
            p=0.9,
        ),

        A.OneOf(
            [
                A.RandomContrast(p=1),
                A.HueSaturationValue(p=1),
            ],
            p=0.9,
        ),
        A.Lambda(mask=round_clip_0_1)
    ]
    return A.Compose(train_transform)


def get_validation_augmentation():
    """Add paddings to make image shape divisible by 32"""
    test_transform = [
        A.PadIfNeeded(384, 480)
    ]
    return A.Compose(test_transform)

def get_preprocessing(preprocessing_fn):
    """Construct preprocessing transform
    
    Args:
        preprocessing_fn (callbale): data normalization function 
            (can be specific for each pretrained neural network)
    Return:
        transform: albumentations.Compose
    
    """
    
    _transform = [
        A.Lambda(image=preprocessing_fn),
    ]
    return A.Compose(_transform)

def inference(model_name, image_folder_path):
    # TODO: Remove below folder empty code
    # We need to create a folder for every image bcoz we need a placeholder
    # for using the below Dataset Class.
    files = glob.glob(os.path.join(os.path.sep,f"{config.IMAGE_PATH}","*"))
    for f in files:
        os.remove(f)

    # wrap our image inside the Dataset wrapper used for training,
    # TODO: remove this and add custom pipeline for preprocessing.
    trial_dataset = Dataset(
    image_folder_path, 
    image_folder_path, 
    classes=CLASSES, 
    augmentation=get_validation_augmentation(),
    preprocessing=get_preprocessing(preprocess_input),
    )


    print(model_name)
    if model_name=="unet":
        model = modelUnet
    elif model_name=="featurepyramidnetwork":
        model = modelFPN
    elif model_name=="linknet":
        model = modelLinknet
            
    # model.load_weights(model_path) 

    # trial folder must have only one image. hence the [0]
    image, gt_mask = trial_dataset[0]
    image = np.expand_dims(image, axis=0)
    pr_mask = model.predict(image).round()
    #print(pr_mask.shape)
    #print(pr_mask[0].shape)
    # make image back to normal
    image=denormalize(image.squeeze())
    gt_mask=gt_mask[..., 0].squeeze()
    pr_mask=pr_mask[..., 0].squeeze()
    # pr_mask = pr_mask[...,0][0]
    #print(final_image.shape)
    # print(gt_mask.shape)
    # print(pr_mask.shape)
    # print(image.shape)
    # DEBUG: 
    # visualize(
    #     image=image,
    #     gt_mask=gt_mask,
    #     pr_mask=pr_mask,
    # )

    return pr_mask,gt_mask



if __name__=="__main__":
    pass
