# services/shared_config.py

# This dictionary is the single source of truth for all action attributes.
# Both the dataset_generator and the quality_service will import from this file.
ATTRIBUTE_DEFINITIONS = {
    'walking_behavior': {
        'options': ['unknown', 'normal_walk', 'fast_walk', 'slow_walk', 'standing_still', 'jogging', 'window_shopping']
    },
    'phone_usage': {
        'options': ['unknown', 'no_phone', 'talking_phone', 'texting', 'taking_photo', 'listening_music']
    },
    'social_interaction': {
        'options': ['unknown', 'alone', 'talking_companion', 'group_walking', 'greeting_someone', 'asking_directions', 'avoiding_crowd']
    },
    'carrying_items': {
        'options': ['unknown', 'empty_hands', 'shopping_bags', 'backpack', 'briefcase_bag', 'umbrella', 'food_drink', 'multiple_items']
    },
    'street_behavior': {
        'options': ['unknown', 'sidewalk_walking', 'crossing_street', 'waiting_signal', 'looking_around', 'checking_map', 'entering_building', 'exiting_building']
    },
    'posture_gesture': {
        'options': ['unknown', 'upright_normal', 'looking_down', 'looking_up', 'hands_in_pockets', 'arms_crossed', 'pointing_gesture', 'bowing_gesture']
    },
    'clothing_style': {
        'options': ['unknown', 'business_attire', 'casual_wear', 'tourist_style', 'school_uniform', 'sports_wear', 'traditional_wear']
    },
    'time_context': {
        'options': ['unknown', 'rush_hour', 'leisure_time', 'shopping_time', 'tourist_hours', 'lunch_break', 'evening_stroll']
    }
}