import random
from typing import List, Dict, Any, Optional
from collections import defaultdict


class AssignmentGenerator:
    """
    Service for dynamically generating annotation task assignments with overlap.
    Replaces static JSON configuration with a dynamic approach.
    """

    def __init__(self):
        # This service is now stateless and doesn't load a config file
        pass

    def generate_random_assignments(
            self,
            clips: List[str],
            annotators: List[str],
            overlap_percentage: int
    ) -> Dict[str, List[str]]:
        """
        Generates a random assignment plan with a specified overlap.

        Args:
            clips: A list of all available clip filenames (e.g., ['1_clip_001.zip']).
            annotators: A list of annotator usernames.
            overlap_percentage: The percentage of clips that should be assigned to a second annotator.

        Returns:
            A dictionary mapping annotator usernames to their assigned clips.
            Example: {'annotator1': ['clipA.zip', 'clipB.zip'], ...}
        """
        if not clips or not annotators:
            raise ValueError("Clips and annotators list cannot be empty.")

        num_annotators = len(annotators)
        num_clips = len(clips)

        # Ensure clips are randomly shuffled for a truly random assignment
        random.shuffle(clips)

        assignments = defaultdict(list)

        # Step 1: Distribute all clips to a primary annotator
        for i, clip in enumerate(clips):
            primary_annotator = annotators[i % num_annotators]
            assignments[primary_annotator].append(clip)

        # Step 2: Handle overlap
        num_overlap_clips = int(num_clips * (overlap_percentage / 100))
        overlap_clips = random.sample(clips, k=min(num_overlap_clips, num_clips))

        for clip in overlap_clips:
            # Find the primary annotator who was assigned this clip
            primary_annotator = next(
                (ann for ann, assigned_clips in assignments.items() if clip in assigned_clips),
                None
            )

            # Select a second, random annotator for the overlap, ensuring it's not the primary one
            available_overlap_annotators = [ann for ann in annotators if ann != primary_annotator]

            if available_overlap_annotators:
                overlap_annotator = random.choice(available_overlap_annotators)
                assignments[overlap_annotator].append(clip)

        return dict(assignments)