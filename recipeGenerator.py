import random
import json


# ------------------------------------------------------------------ #
#  Constants                                                           #
# ------------------------------------------------------------------ #

SIMILARITY_THRESHOLD    = 0.5
CANDIDATE_POOL_SIZE     = 20
REEL_DURATION_OPTIONS   = [15, 30, 60]
SEGMENT_DURATION_MIN    = 2.0
SEGMENT_DURATION_MAX    = 5.0
PHOTO_DISPLAY_DURATION  = 3.0
MAX_ATTEMPTS            = 10


# ------------------------------------------------------------------ #
#  Public API                                                          #
# ------------------------------------------------------------------ #

def buildRecipe(db, use_all_photos=False):
    """
    Main entry point.

    Parameters
    ----------
    db              : SQLHandler instance
    use_all_photos  : if True, every photo in the library is included in the
                      reel (in a random order). The target duration is ignored
                      and duplicate-checking is skipped since the recipe is
                      deterministically derived from the full library.

    Returns (recipe, None) on success or (None, error_string) on failure.
    """
    all_clips = db.get_clips_weighted()

    if not all_clips:
        return None, "No clips in database. Import some media first."

    all_clips = [dict(clip) for clip in all_clips]

    photos = [c for c in all_clips if c["media_type"] == "photo"]
    videos = [c for c in all_clips if c["media_type"] == "video"]

    if not photos and not videos:
        return None, "No usable clips found."

    # ---- "Use all photos" mode ---- #
    if use_all_photos:
        if not photos:
            return None, "No photos found in the library."

        random.shuffle(photos)
        recipe = [_buildPhotoSegment(p, PHOTO_DISPLAY_DURATION) for p in photos]
        recipe = [seg for seg in recipe if seg is not None]

        if not recipe:
            return None, "Could not build segments from photos."

        return recipe, None

    # ---- Normal random mode ---- #
    target_duration = random.choice(REEL_DURATION_OPTIONS)

    past_reels   = db.get_all_reels()
    past_recipes = []
    for reel in past_reels:
        try:
            past_recipes.append(json.loads(reel["recipe"]))
        except Exception:
            continue

    for attempt in range(MAX_ATTEMPTS):
        recipe = _selectClips(photos, videos, target_duration)

        if recipe and not _isTooSimilar(recipe, past_recipes):
            return recipe, None

    return None, (
        "Couldn't generate a unique reel after several attempts. "
        "Try importing more media or lowering the similarity threshold."
    )


def recipeToJson(recipe):
    return json.dumps(recipe)


def recipeFromJson(recipe_json):
    return json.loads(recipe_json)


# ------------------------------------------------------------------ #
#  Internal helpers                                                    #
# ------------------------------------------------------------------ #

def _selectClips(photos, videos, target_duration):
    recipe         = []
    total_duration = 0.0

    candidate_pool = []
    if photos:
        candidate_pool += photos[:CANDIDATE_POOL_SIZE]
    if videos:
        candidate_pool += videos[:CANDIDATE_POOL_SIZE]

    if not candidate_pool:
        return None

    random.shuffle(candidate_pool)

    for clip in candidate_pool:
        if total_duration >= target_duration:
            break

        remaining = target_duration - total_duration

        if clip["media_type"] == "photo":
            segment = _buildPhotoSegment(clip, remaining)
        else:
            segment = _buildVideoSegment(clip, remaining)

        if segment:
            recipe.append(segment)
            total_duration += segment["display_duration"]

    if total_duration < target_duration * 0.8:
        return None

    return recipe


def _buildPhotoSegment(clip, remaining_duration):
    display_duration = min(PHOTO_DISPLAY_DURATION, remaining_duration)

    if display_duration < 0.5:
        return None

    return {
        "clip_id":          clip["id"],
        "media_type":       "photo",
        "path":             clip["path"],
        "start_time":       None,
        "end_time":         None,
        "display_duration": round(display_duration, 2)
    }


def _buildVideoSegment(clip, remaining_duration):
    clip_available = clip["end_time"] - clip["start_time"]

    if clip_available < SEGMENT_DURATION_MIN:
        return None

    max_segment = min(SEGMENT_DURATION_MAX, clip_available, remaining_duration)

    if max_segment < SEGMENT_DURATION_MIN:
        return None

    segment_duration = round(random.uniform(SEGMENT_DURATION_MIN, max_segment), 2)
    latest_start     = clip["end_time"] - segment_duration
    start            = round(random.uniform(clip["start_time"], latest_start), 2)
    end              = round(start + segment_duration, 2)

    return {
        "clip_id":          clip["id"],
        "media_type":       "video",
        "path":             clip["path"],
        "start_time":       start,
        "end_time":         end,
        "display_duration": segment_duration
    }


def _isTooSimilar(new_recipe, past_recipes):
    new_ids = set(seg["clip_id"] for seg in new_recipe)

    for past_recipe in past_recipes:
        past_ids = set(seg["clip_id"] for seg in past_recipe)
        union    = len(new_ids | past_ids)

        if union == 0:
            continue

        if len(new_ids & past_ids) / union >= SIMILARITY_THRESHOLD:
            return True

    return False
