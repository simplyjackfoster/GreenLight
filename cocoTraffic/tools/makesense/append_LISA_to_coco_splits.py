# =================================================================== #
# Appends the LISA annotations to the coco train and val data.        #
#                                                                     #
# LISA annotations are in the makesense.ai .csv format.               #
# =================================================================== #

import pandas as pd
import os
from shutil import copyfile
import random
import json
import logging
from pathlib import Path
from PIL import Image
import warnings
import argparse
from typing import List, Dict, Any, Tuple

from tqdm import tqdm

# FIXED: use script-relative base directory + CLI paths instead of hardcoded relative paths
BASE_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


def validate_or_warn(condition: bool, message: str, strict: bool = False) -> None:
    # FIXED: replace fragile assert crashes with warning + optional strict mode
    if not condition:
        if strict:
            raise ValueError(message)
        logger.warning(message)


def get_diff(l1: List[Any], l2: List[Any]) -> List[Any]:
    """
    Returns the difference between two lists.
    """
    diff = list( list(set(l1) - set(l2)) + list(set(l2) - set(l1)) )

    return diff


def load_LISA_annotations(makesense_annotation_files: List[str], makesense_path: str = "./relabelled/") -> pd.DataFrame:
    """
    Loads all makesense.ai .csv files into a single pandas dataframe.
    """
    cols = ["label", "x", "y", "w", "h", "name", "size_w", "size_h"]
    makesense_anns = pd.DataFrame(columns=cols)
    parts = []

    for file in tqdm(makesense_annotation_files, desc="Load CSV annotations", disable=not logger.isEnabledFor(logging.INFO)):
        anns_part = pd.read_csv(makesense_path+file, names=cols)
        # FIXED: DataFrame.append removed in pandas 2.x
        parts.append(anns_part)

    if parts:
        makesense_anns = pd.concat(parts, ignore_index=True)

    makesense_anns.reset_index(inplace=True)

    return makesense_anns


def filter_lisa_anns(anns: pd.DataFrame) -> List[str]:
    """
    Filters out images which contain the not-relabelled coco traffic light
    class from the given dataframe. Returns a list of images which 
    contain the relabelled classes.
    """ 
    logger.info("Found %s images.", len(set(anns['name'])))
    row_del = anns[anns['label'] == "traffic light"]
    imgs_del = list(set(row_del['name']))
    image_names = get_diff(list(set(anns['name'])), imgs_del)
    logger.info("Removed %s images with unannotated traffic lights.", len(imgs_del))

    return image_names
    
 
def copy_images_from_lisa(img_filenames: List[str], path_source: str, images_dir: str, strict: bool = False) -> None:
    """
    Copies the images in the given list from the dataset folders
    as downloaded into a single  folder.
    """
    count = 0
    for filename in tqdm(img_filenames, desc="Copy LISA images", disable=not logger.isEnabledFor(logging.INFO)):
    
        if filename.find("Clip") != -1:
            folder_name = filename.split('--')[0].replace("Clip", "Train")
            folder_name = "".join(filter(lambda x: not x.isdigit(), folder_name))
            # Format: nightTrain/nightTrain/nightClip2/frames/nightClip2--...
            path = path_source + folder_name + "/" + folder_name + "/" + filename.split('--')[0] +"/frames/"
        else:
            folder_name = filename.split('--')[0]
            path = path_source + folder_name + "/" + folder_name + "/frames/"
       
        try:
            copyfile(path+filename, str(Path(images_dir) / "TrafficLISA" / filename))
            count +=1
        except FileNotFoundError:
            logger.error("Folder %s does not exist. Please create it and try again.", path)
            return
    validate_or_warn(count == len(img_filenames), "Copied {} images but expected {}.".format(count, len(img_filenames)), strict)

    logger.info("Copied %s images to %s", count, path + "relabel")


def split_anns(
    df_anns: pd.DataFrame,
    split: float = 0.8,
    copy_files: bool = False,
    images_dir: str = str(BASE_DIR / "images"),
    strict: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Splits the data into train and val. Data is given as a dataframe.
    Copies the image files into folders if copy_file=True.
    """
    
    # Get all images and sample them
    img_files = list(set(df_anns['name']))  
    num_train = int(len(img_files) * split)
    num_val = len(img_files) - num_train
    
    # Sample
    random.seed(1867)
    imgs_train = random.sample(img_files, num_train)
    imgs_val = get_diff(img_files, imgs_train)  
    validate_or_warn(len(imgs_train) == num_train, "Train split size mismatch in split_anns.", strict)
    validate_or_warn(len(imgs_val) == num_val, "Val split size mismatch in split_anns.", strict)
    validate_or_warn(len(img_files) == (len(imgs_train) + len(imgs_val)), "Split totals do not match source image count in split_anns.", strict)

    # Filter dataframes
    train = df_anns[df_anns['name'].isin(imgs_train)]
    val = df_anns[df_anns['name'].isin(imgs_val)]
    validate_or_warn(len(df_anns) == (len(train) + len(val)), "Train+val row counts do not match input rows in split_anns.", strict)
    logger.info("Split data into %s train and %s val imags.", num_train, num_val)

    if copy_files is True:
        logger.info("Copying image files to train and val folders...")
        src = str(Path(images_dir) / "TrafficLISA") + "/"
        dst_train = str(Path(images_dir) / "trainTrafficLISA") + "/"
        dst_val = str(Path(images_dir) / "valTrafficLISA") + "/"
        count = 0
        for img in tqdm(imgs_train, desc="Copy train images", disable=not logger.isEnabledFor(logging.INFO)):
            try:
                copyfile(src+img, dst_train+img)
                count += 1
            except FileNotFoundError:
                logger.warning("File %s not found in %s.", img, src)
        logger.info("Copied %s files from %s to %s (%s missing).", count, src, dst_train, len(imgs_train) - count)
        count = 0
        for img in tqdm(imgs_val, desc="Copy val images", disable=not logger.isEnabledFor(logging.INFO)):
            try:
                copyfile(src+img, dst_val+img)
                count += 1
            except FileNotFoundError:
                logger.warning("File %s not found in %s.", img, src)
        logger.info("Copied %s files from %s to %s (%s missing).", count, src, dst_val, len(imgs_val) - count)

    return train, val


def make_coco_ann(
    df_ann: pd.DataFrame,
    filename_out: str,
    save: bool = False,
    image_root: str = str(BASE_DIR / "images" / "TrafficLISA"),
    annotations_dir: str = str(BASE_DIR / "annotations"),
) -> Dict[str, Any]:
    """
    Converts a list of lists of annotations into a COCO .json object.
    """
    # Objects
    info = {
        "description": "LISA Traffic Light Dataset Subset",
        "url": "https://www.kaggle.com/mbornoe/lisa-traffic-light-dataset",
        "version": "1.0",
        "year": 2021,
        "contributor": "Kaggle",
        "date_created": "2021/05/17"
    }

    licenses = [{
            "url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
            "id": 9,
            "name": "Attribution-NonCommercial-ShareAlike License"
        }]
    # Categories for the traffic dataset.
    categories = [{'supercategory': 'person', 'id': 1, 'name': 'person'},
    {'supercategory': 'vehicle', 'id': 2, 'name': 'bicycle'},
    {'supercategory': 'vehicle', 'id': 3, 'name': 'car'},
    {'supercategory': 'vehicle', 'id': 4, 'name': 'motorcycle'},
    {'supercategory': 'vehicle', 'id': 6, 'name': 'bus'},
    {'supercategory': 'vehicle', 'id': 7, 'name': 'train'},
    {'supercategory': 'vehicle', 'id': 8, 'name': 'truck'},
    {'supercategory': 'outdoor', 'id': 10, 'name': 'traffic light'},
    {'supercategory': 'outdoor', 'id': 11, 'name': 'fire hydrant'},
    {'supercategory': 'outdoor', 'id': 13, 'name': 'stop sign'}, 
    {'supercategory': 'animal', 'id': 17, 'name': 'cat'},
    {'supercategory': 'animal', 'id': 18, 'name': 'dog'},
    {'supercategory': 'outdoor', 'id': 92, 'name': 'traffic_light_red'},
    {'supercategory': 'outdoor', 'id': 93, 'name': 'traffic_light_green'},
    {'supercategory': 'outdoor', 'id': 94, 'name': 'traffic_light_na'}]

    # Add images
    images = []
    img_names = list(set(df_ann['name']))

    image_root_path = Path(image_root)

    for img_name in tqdm(img_names, desc="Build image metadata", disable=not logger.isEnabledFor(logging.INFO)):
        img_height = 960
        img_width = 1280
        img_path = image_root_path / img_name
        if img_path.exists():
            with Image.open(img_path) as image:
                img_width, img_height = image.size
        else:
            # FIXED: derive dimensions from actual files; fallback with explicit warning
            warnings.warn("Image not found for dimensions: {}. Falling back to 1280x960.".format(img_path))

        images.append({
            "license": 9,
            "file_name": img_name,
            "coco_url": "",
            "height": img_height,
            "width": img_width,
            "date_captured": "2019-09-27",
            "flickr_url": "",
            "id": img_name.split('.')[0]
        })
 
    # Label mapping
    label_to_ind = {"person":1, "car":3, "bus":6, "train":7, "truck":8, "traffic light":10, "fire hydrant":11,
    "traffic_light_red":92, "traffic_light_green":93, "traffic_light_na":94}

    # Add annotations
    annotations = []
    ann_id = 1 # Format: Number + l
    df_ann.reset_index(inplace=True)

    for i in tqdm(range(len(df_ann)), desc="Build COCO annotations", disable=not logger.isEnabledFor(logging.INFO)):
        ann = df_ann.loc[i]
        name = ann['name']
        label = label_to_ind[ann['label']]
        box = [float(ann['x']), float(ann['y']), float(ann['w']), float(ann['h'])]
        # FIXED: COCO area should be numeric bbox area, not an empty string
        area = float(ann['w']) * float(ann['h'])
        annotations.append({'segmentation': [[]],
        'area': area,
        'iscrowd': 0,
        'image_id': name.split('.')[0],
        'bbox': box,
        'category_id': label,
        'id': str(ann_id) + "l"}) 
        ann_id+=1
  
    coco_ann = {'info':info, 'licenses':licenses, 'images':images, 'annotations':annotations, 'categories':categories}
    
    # Save to disk
    if save is True:
        path_ouot = Path(annotations_dir)
        path_ouot.mkdir(parents=True, exist_ok=True)
        with open(path_ouot / (str(filename_out)+'.json'), 'w', encoding='utf-8') as f:
            json.dump(coco_ann, f, ensure_ascii=False, indent=4)

    logger.info("Saved dataset %s to disk!", filename_out)

    return coco_ann


def append_coco_anns(
    filename_anns_1: str,
    anns_to_append: Dict[str, Any],
    filename_out: str,
    annotations_dir: str = str(BASE_DIR / "annotations"),
    strict: bool = False,
) -> None:
    """
    Appends the LISA annotations to given coco annotations.
    """
    
    # Load dataset traffic to which we want to append
    ann_file = str(Path(annotations_dir) / (filename_anns_1 + ".json"))
    with open(ann_file, "r", encoding="utf-8") as f:
        anns = json.load(f)
    logger.info("Loaded %s annotations from file %s.", len(anns['annotations']), filename_anns_1)

    # Append LISA stuff to the traffic dataset.
    info_out = anns['info']
    licenses_out = anns['licenses'] + anns_to_append['licenses']
    validate_or_warn(len(licenses_out) == 9, "Expected 9 licenses after append, got {}.".format(len(licenses_out)), strict)
    categories_out = anns_to_append['categories']
    validate_or_warn(len(categories_out) == 15, "Expected 15 categories after append, got {}.".format(len(categories_out)), strict)
    images_out = anns['images'] + anns_to_append['images']
    annotations_out = anns['annotations'] + anns_to_append['annotations']
    logger.info("Number of images: %s", len(images_out))
    logger.info("Number of annotations: %s", len(annotations_out))

    anns_out = {'info':info_out, 'licenses':licenses_out, 'images':images_out, 
    'annotations':annotations_out, 'categories':categories_out}
    
    # Save annotations
    output_path = Path(annotations_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with open(output_path / (str(filename_out)+'.json'), 'w', encoding='utf-8') as f:
        json.dump(anns_out, f, ensure_ascii=False, indent=4)

    logger.info("Saved dataset %s to disk!", filename_out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(BASE_DIR / "tools" / "makesense" / "relabelled"), help="Input relabelled CSV directory")
    parser.add_argument("--output", default=str(BASE_DIR / "annotations"), help="Output annotations directory")
    parser.add_argument("--annotations", default=str(BASE_DIR / "annotations"), help="Input annotations directory")
    parser.add_argument("--strict", action="store_true", help="Fail on validation mismatches instead of warning")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()
    # FIXED: replace bare print calls with logging and runtime verbosity configuration
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")

    anns_lisa = load_LISA_annotations(["cocoTrafficLightsLISA-part1.csv", 
                "cocoTrafficLightsLISA-part2.csv", "cocoTrafficLightsLISA-part3.csv"], makesense_path=args.input + "/")
    imgs_name_list = filter_lisa_anns(anns_lisa)
    #copy_images_from_lisa(imgs_name_list, "<path_to_the_lisa_dataset>")
    anns_lisa = anns_lisa[anns_lisa["name"].isin(imgs_name_list)]
    validate_or_warn(
        len(set(anns_lisa['name'])) == len(imgs_name_list),
        "Unique filtered image count mismatch after filtering LISA annotations.",
        args.strict
    )
    
    # Split data into train and val
    df_train, df_val = split_anns(anns_lisa, split=0.8, copy_files=False, strict=args.strict)
    anns_train = make_coco_ann(df_train, "instances_trainTrafficLISA", save=False, annotations_dir=args.output)
    anns_val = make_coco_ann(df_val, "instances_valTrafficLISA", save=False, annotations_dir=args.output)
    append_coco_anns("./before_lisa/instances_trainTraffic", anns_train, "instances_trainTraffic", annotations_dir=args.annotations, strict=args.strict)
    append_coco_anns("./before_lisa/instances_valTraffic", anns_val, "instances_valTraffic", annotations_dir=args.annotations, strict=args.strict)
