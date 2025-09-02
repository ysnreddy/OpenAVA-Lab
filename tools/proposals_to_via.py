import os
import pickle
import argparse
from collections import defaultdict
import cv2
from tqdm import tqdm
import re
from via3_tool import Via3Json  # Make sure via3_tool.py is in the same directory


def create_via_file_for_video(video_id, frames_data, video_frame_path, attributes_dict):
    """
    Creates a VIA JSON file with each frame as a separate view, using absolute coordinates.
    """
    via_json_path = os.path.join(video_frame_path, f"{video_id}_via.json")
    via3 = Via3Json(via_json_path, mode='dump')

    # Add a 'person_id' attribute for context.
    # FIX: Added a dummy option to satisfy the via3_tool.py assertion.
    person_id_attr = {
        '9': dict(aname='person_id', type=1, options={'_': ''}, default_value='-1', anchor_id='FILE1_Z0_XY1')}
    combined_attributes = {**attributes_dict, **person_id_attr}

    action_attributes = {attr_id: '' for attr_id in attributes_dict.keys()}

    files_dict = {}
    metadatas_dict = {}
    file_id_counter = 1

    # Sort frames numerically to ensure correct order in VIA
    # This regex finds the number in frame filenames like '..._frame_0001.jpg'
    sorted_frame_names = sorted(frames_data.keys(), key=lambda f: int(re.search(r'_(\d{4,})\.jpg$', f).group(1)))

    for frame_filename in sorted_frame_names:
        keyframe_path = os.path.join(video_frame_path, frame_filename)
        if not os.path.exists(keyframe_path):
            continue

        current_file_id_str = str(file_id_counter)
        files_dict[current_file_id_str] = {'fname': frame_filename, 'type': 2}

        # Get detections for this specific frame
        detections = frames_data.get(frame_filename, [])

        for detection_idx, bbox_data in enumerate(detections, 1):
            # ✨ FIX: The pkl file now stores raw absolute coordinates [x1, y1, x2, y2, score, track_id]
            abs_x1, abs_y1, abs_x2, abs_y2 = bbox_data[0], bbox_data[1], bbox_data[2], bbox_data[3]
            track_id = bbox_data[5]

            # Convert from (x1, y1, x2, y2) to VIA's (x, y, width, height) format
            width = abs_x2 - abs_x1
            height = abs_y2 - abs_y1

            # Create the attribute dictionary for this box
            av_dict = action_attributes.copy()
            av_dict['9'] = str(track_id)  # Set the person_id attribute

            metadata_key = f"v{current_file_id_str}_{detection_idx}"
            metadatas_dict[metadata_key] = {
                "vid": current_file_id_str,
                "xy": [2, float(abs_x1), float(abs_y1), float(width), float(height)],
                "av": av_dict
            }
        file_id_counter += 1

    if not files_dict:
        return

    vid_list = list(files_dict.keys())
    via3.dumpPrejects(vid_list)
    via3.dumpConfigs()
    via3.dumpAttributes(combined_attributes)
    via3.dumpFiles(files_dict)
    via3.dumpMetedatas(metadatas_dict)

    views_dict = {}
    for i, vid in enumerate(vid_list):
        views_dict[vid] = defaultdict(list)
        views_dict[vid]['fid_list'].append(str(i + 1))

    via3.dumpViews(views_dict)
    via3.dempJsonSave()


def main():
    parser = argparse.ArgumentParser(
        description="Create VIA JSON files with person_id from a frame-based dense proposal file.")
    parser.add_argument('--pickle_path', type=str, required=True,
                        help="Path to the frame-based dense_proposals.pkl file.")
    parser.add_argument('--frame_dir', type=str, required=True,
                        help="Root directory containing extracted frame subdirectories.")
    args = parser.parse_args()

    try:
        with open(args.pickle_path, 'rb') as f:
            proposals_data = pickle.load(f)
    except FileNotFoundError:
        print(f"❌ Error: Pickle file not found at {args.pickle_path}")
        return

    # Your 8 action attributes
    attributes_dict = {
        '1': dict(aname='walking_behavior', type=2,
                  options={'0': 'normal_walk', '1': 'fast_walk', '2': 'slow_walk', '3': 'standing_still',
                           '4': 'jogging', '5': 'window_shopping'}, default_option_id="", anchor_id='FILE1_Z0_XY1'),
        '2': dict(aname='phone_usage', type=2,
                  options={'0': 'no_phone', '1': 'talking_phone', '2': 'texting', '3': 'taking_photo',
                           '4': 'listening_music'}, default_option_id="", anchor_id='FILE1_Z0_XY1'),
        '3': dict(aname='social_interaction', type=2,
                  options={'0': 'alone', '1': 'talking_companion', '2': 'group_walking', '3': 'greeting_someone',
                           '4': 'asking_directions', '5': 'avoiding_crowd'}, default_option_id="",
                  anchor_id='FILE1_Z0_XY1'),
        '4': dict(aname='carrying_items', type=2,
                  options={'0': 'empty_hands', '1': 'shopping_bags', '2': 'backpack', '3': 'briefcase_bag',
                           '4': 'umbrella', '5': 'food_drink', '6': 'multiple_items'}, default_option_id="",
                  anchor_id='FILE1_Z0_XY1'),
        '5': dict(aname='street_behavior', type=2,
                  options={'0': 'sidewalk_walking', '1': 'crossing_street', '2': 'waiting_signal',
                           '3': 'looking_around', '4': 'checking_map', '5': 'entering_building',
                           '6': 'exiting_building'}, default_option_id="", anchor_id='FILE1_Z0_XY1'),
        '6': dict(aname='posture_gesture', type=2,
                  options={'0': 'upright_normal', '1': 'looking_down', '2': 'looking_up', '3': 'hands_in_pockets',
                           '4': 'arms_crossed', '5': 'pointing_gesture', '6': 'bowing_gesture'}, default_option_id="",
                  anchor_id='FILE1_Z0_XY1'),
        '7': dict(aname='clothing_style', type=2,
                  options={'0': 'business_attire', '1': 'casual_wear', '2': 'tourist_style', '3': 'school_uniform',
                           '4': 'sports_wear', '5': 'traditional_wear'}, default_option_id="",
                  anchor_id='FILE1_Z0_XY1'),
        '8': dict(aname='time_context', type=2,
                  options={'0': 'rush_hour', '1': 'leisure_time', '2': 'shopping_time', '3': 'tourist_hours',
                           '4': 'lunch_break', '5': 'evening_stroll'}, default_option_id="", anchor_id='FILE1_Z0_XY1')
    }

    # The new proposals_data is a dict where keys are video_ids
    print(f"Found proposals for {len(proposals_data)} unique video clips.")
    for video_id, frames_data in tqdm(proposals_data.items(), desc="Generating VIA files"):
        video_specific_frame_dir = os.path.join(args.frame_dir, video_id)
        if os.path.isdir(video_specific_frame_dir):
            # Pass frames_data directly, which is the dictionary of frames for this video
            create_via_file_for_video(video_id, frames_data, video_specific_frame_dir, attributes_dict)

    print("\n🎉 All VIA JSON files have been generated.")


if __name__ == "__main__":
    main()
