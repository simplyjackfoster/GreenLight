from pycocotools.coco import COCO
import json
import logging
import cv2 as cv
import argparse
from pathlib import Path
from typing import Any, Dict, List, Set

from tqdm import tqdm

# FIXED: script-relative path defaults + CLI path overrides
BASE_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)

# Import annotations (check)
# Create loop to loop through images (check)
# Show image (check)
# Allow going backwards (check)
# Modify label category (check)
# Save modified annotations (check)
# Save progress (check)
# Save weird images (check)
# Import tags (check)
# Print progress (check)

def load_ann(filepath: str, saveFile: str) -> COCO:
    try:
        coco = COCO(saveFile + ".json")
        logger.info("Previous session found. Reloading relabelled annotations")
        return coco
    except IOError:
        try:
            coco = COCO(filepath)
            logger.info("Unable to find previous session. Starting off from original file")
            return coco
        except IOError:
            raise Exception("Could not find original file")
    


def save_tagged(target_filepath: str, tagged_images: Set[str]) -> None:
    tags = sorted(list(tagged_images))

    with open(target_filepath + ".json", 'w', encoding='utf-8') as f:
        json.dump(tags, f, ensure_ascii=False, indent=4)

def load_tagged(filepath: str) -> Set[str]:
    try:
        with open(filepath + ".json", 'r') as f:
            return set(json.load(f))
    except IOError:
        logger.warning("Unable to load tags. Starting off with all images untagged.")
        return set()

def save_point(target_filepath: str, imgId: Any) -> None:
    with open(target_filepath + ".json", 'w') as f:
        json.dump(imgId, f)

def load_point(filepath: str, anns: List[Dict[str, Any]]) -> int:
    try:
        with open(filepath + ".json", 'r') as f:
            imgId = str(json.load(f)).rstrip()
    except IOError:
        logger.warning("Unable to load last viewed image. Starting from beginning.")
        return 0

    if str(imgId) == str(-1):
        logger.info("Previous session completed going through all annotations. Starting from beginning")
        return 0
    
    for i in range(len(anns)):
        if str(imgId) == str(anns[i]['image_id']):
            return i

    logger.warning("Unable to find matching image id in annotations. Starting from beginning")
    return 0


def box_xywh_to_xyxy(x: List[float]) -> List[int]:
    # Converts bounding boxes to (x1, y1, x2, y2) coordinates of top left and bottom right corners
    x_c, y_c, w, h = x
    # Offset for display purposes
    b = [(x_c), (y_c),
        (x_c + w), (y_c + h)]
    box = list(map(int, map(round, b)))
    return box


def save_dataset(original_filepath: str, target_filepath: str, anns: List[Dict[str, Any]], cats: List[Dict[str, Any]]) -> None:

    # Load dataset val to get structure
    with open(original_filepath, "r", encoding="utf-8") as f:
        orig_file = json.load(f)

    # Make final dictionary
    dataset = dict.fromkeys(orig_file.keys())
    dataset['info'] = orig_file['info']
    dataset['licenses'] = orig_file['licenses']
    dataset['categories'] = cats
    dataset['annotations'] = anns
    dataset['images'] = orig_file['images']

    with open(target_filepath + '.json', 'w', encoding='utf-8') as f:
        json.dump(dataset, f, ensure_ascii=False, indent=4)

    logger.info("Saved dataset %s.json to disk!", target_filepath)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(BASE_DIR / "images"), help="Images root directory")
    parser.add_argument("--output", default=str(BASE_DIR / "annotations"), help="Output annotations directory")
    parser.add_argument("--annotations", default=str(BASE_DIR / "annotations"), help="Input annotations directory")
    parser.add_argument("--data-type", default="Traffic", help="Dataset suffix for instances_<type>.json")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()
    # FIXED: replace print with logging and add runtime verbosity control
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")

    cat_show = [10, 92, 93, 94]  # Categories ids that you want shown and relabelled
    #cat_show = [10]  # Categories ids that you want shown and relabelled

    # COCO dataset path
    dataType = args.data_type

    # Annotations file  
    annFile = str(Path(args.annotations) / ('instances_' + dataType + '.json'))

    # Save file
    saveFile = str(Path(args.output) / ('instances_' + dataType + 'Relabelled'))
    tagFile = str(Path(args.output) / "labelTool" / ('instances_' + dataType + 'Tagged'))
    progressFile = str(Path(args.output) / "labelTool" / ('instances_' + dataType + 'LastSave'))
    Path(Path(args.output) / "labelTool").mkdir(parents=True, exist_ok=True)

    # Images folder
    imgDir = str(Path(args.input) / dataType) + '/'

    # Import from annotations file
    

    coco=load_ann(annFile, saveFile)

    cats = coco.loadCats(coco.getCatIds())

    if len(cats) == 80:
        cats.append({'supercategory': 'outdoor', 'id': 92, 'name': 'traffic_light_red'})
        cats.append({'supercategory': 'outdoor', 'id': 93, 'name': 'traffic_light_green'})
        cats.append({'supercategory': 'outdoor', 'id': 94, 'name': 'traffic_light_na'})
    else:
        if cats[80]['name'] != 'traffic_light_red' or \
            cats[81]['name'] != 'traffic_light_green' or \
            cats[82]['name'] != 'traffic_light_na':
            raise Exception("Error: Categories mismatched. Check categories to make sure the 92nd category id is traffic_light_red")
    
    nms = [cat['name'] for cat in cats]
    catId_to_catName = {cats[x]['id']: cats[x]['name'] for x in range(len(cats))}

    # Load image Ids
    catIds = coco.getCatIds(catNms=nms)
    imgIdsAll = coco.getImgIds()
    imgIds = imgIdsAll
    logger.info("Number of images: %s", len(imgIds))

    # Load annotations
    annIds = coco.getAnnIds(imgIds)
    anns = coco.loadAnns(annIds)
    logger.info("Number of annotations: %s", len(anns))

    # Initialize variables
    annId_i = load_point(progressFile, anns)
    ann_counter = 0  # To tell user how many annotations are left
    save_flag = False
    tagged_images = load_tagged(tagFile)  # (Set) of saved tagged images

    logger.warning("The available commands are as follows: (save), (q) quit, (z) back, (tag) tag image, () skip, (1)(r) label red, (2)(g) label green, (3)(n) label na, (0)(-) label back to traffic light")
    logger.warning("Type help to repeat these commands")
    
    # FIXED: group by image_id so each image is loaded once (instead of once per annotation)
    grouped_ann_indices = {}
    for idx, ann in enumerate(tqdm(anns, desc="Index annotations", disable=not logger.isEnabledFor(logging.INFO))):
        if ann['category_id'] in cat_show:
            grouped_ann_indices.setdefault(ann['image_id'], []).append(idx)
    grouped_items = list(grouped_ann_indices.items())

    start_image_id = anns[annId_i]['image_id'] if len(anns) > 0 else None
    group_i = 0
    for gi, (image_id, _) in enumerate(grouped_items):
        if str(image_id) == str(start_image_id):
            group_i = gi
            break

    ann_pos = 0
    quit_requested = False

    # Main loop
    while group_i < len(grouped_items):
        imgId, ann_indices_for_image = grouped_items[group_i]
        image = cv.imread(imgDir + (str(imgId)+'.jpg').zfill(16))
        if image is None:
            raise Exception("Error: Cannot find image {}".format(imgDir + (str(imgId)+'.jpg').zfill(16)))

        while ann_pos < len(ann_indices_for_image):
            annId_i = ann_indices_for_image[ann_pos]
            ann = anns[annId_i]
            go_backwards = False
            ann_counter += 1
            logger.info("")

            # Give progress status
            if ann_counter >= 10:
                logger.info("You are on annotation %s / %s", str(annId_i + 1), str(len(anns)))
                ann_counter = 0

            b = ann['bbox']
            box = box_xywh_to_xyxy(b)
            logger.info("Current label: %s", catId_to_catName[ann['category_id']])

            # Display bounding box
            offset = 2  # offset bounding boxes to better see object inside
            image_bboxed = image.copy()
            cv.rectangle(image_bboxed, (box[0]-offset, box[1]-offset), (box[2]+offset, box[3]+offset), (252, 3, 219), 2)
            cv.imshow((str(imgId)+'.jpg'), image_bboxed)
            if cv.waitKey(1) == ord("q"):
                quit_requested = True
                break
            
            # Ask user for command
            while True:
                inp = str(input("\nAvailable commands: help, save, q, <blank>, tag, 1, 2, 3, 0, r, g, n, -\n")).rstrip().lower()
                if inp == "":
                    break
                elif inp == "help":
                    logger.warning("The available commands are as follows: (save), (q) quit, (z) back, (tag) tag image, () skip, (1)(r) label red, (2)(g) label green, (3)(n) label na, (0)(-) label back to traffic light")
                elif inp == "q":
                    if save_flag == False:
                        inp = str(input("You haven't saved. Are you sure? (y/n)\n")).rstrip().lower()
                        if inp in ['yes', 'y']:
                            logger.warning("Labels not saved")
                            quit_requested = True
                            break
                    else:
                        quit_requested = True
                        break
                elif inp == "z":
                    go_backwards = True
                    break
                elif inp == "save":
                    save_tagged(tagFile, tagged_images)
                    save_point(progressFile, imgId)
                    save_dataset(annFile, saveFile, anns, cats)
                    save_flag = True
                elif inp == "tag":
                    tagged_images.add((str(imgId)+'.jpg').zfill(16))
                    logger.info("Added tagged image. Make sure to save to save the tag.")
                elif (inp == "r") or (inp == "1"):
                    logger.info("Changed category id to traffic_light_red")
                    anns[annId_i]['category_id'] = 92
                    break
                elif (inp == "g") or (inp == "2"):
                    logger.info("Changed category id to traffic_light_green")
                    anns[annId_i]['category_id'] = 93
                    break
                elif (inp == "n") or (inp == "3"):
                    logger.info("Changed category id to traffic_light_na")
                    anns[annId_i]['category_id'] = 94
                    break
                elif (inp == "-") or (inp == "0"):
                    logger.info("Changed category id back to traffic light")
                    anns[annId_i]['category_id'] = 10
                    break
                else:
                    logger.warning("Invalid command")

            if quit_requested:
                break

            if go_backwards:
                if ann_pos > 0:
                    ann_pos -= 1
                elif group_i > 0:
                    group_i -= 1
                    prev_indices = grouped_items[group_i][1]
                    ann_pos = max(0, len(prev_indices) - 1)
                    break
            else:
                ann_pos += 1

        cv.destroyAllWindows()
        if quit_requested:
            break

        if ann_pos >= len(ann_indices_for_image):
            group_i += 1
            ann_pos = 0


    logger.warning("Completed image labelling")
    
    # End save
    while True:
        inp = str(input("Save?(y/n)\n")).rstrip().lower()
        if inp in ['yes', 'y']:
            save_tagged(tagFile, tagged_images)
            save_point(progressFile, -1)
            save_dataset(annFile, saveFile, anns, cats)
            exit()
        elif inp in ['no', 'n']:
            inp = str(input("Are you sure?(y/n)\n")).rstrip().lower()
            if inp in ['yes', 'y']:
                logger.warning("Labels not saved")
                exit()
