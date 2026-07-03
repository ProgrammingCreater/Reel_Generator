import subprocess
import os
import tempfile
from pathlib import Path
import random

# ------------------------------------------------------------------ #
#  Configuration                                                       #
# ------------------------------------------------------------------ #

# On Mac (after `brew install ffmpeg`) change both of these to just "ffmpeg"
# and "ffprobe". On Windows, point to the full path of your ffmpeg bin folder.
FFMPEG_PATH  = "C:\\Users\\shaya\\Downloads\\PYPY\\ffmpeg-8.1.1-full_build\\ffmpeg-8.1.1-full_build\\bin\\ffmpeg.exe"   # replace with full path on Windows
FFPROBE_PATH = "C:\\Users\\shaya\\Downloads\\PYPY\\ffmpeg-8.1.1-full_build\\ffmpeg-8.1.1-full_build\\bin\\ffprobe.exe"  # replace with full path on Windows

# Example Windows paths — uncomment and update if needed:
# FFMPEG_PATH  = "C:\\ffmpeg\\bin\\ffmpeg.exe"
# FFPROBE_PATH = "C:\\ffmpeg\\bin\\ffprobe.exe"

OUTPUT_FOLDER = Path("databases/outputs")
MUSIC_FOLDER = Path("databases/music")
MUSIC_VOLUME = 0.3   # 0.0 = silent, 1.0 = full volume, 0.3 = quiet background

# Vertical format for Reels / Shorts / TikTok
OUTPUT_WIDTH  = 1080
OUTPUT_HEIGHT = 1920

# Ken Burns zoom speed for photos (higher = faster zoom)
ZOOM_SPEED = 0.0015

# Frames per second for photo clips
PHOTO_FPS = 25

# Video encoding quality (lower = better quality, larger file; 18–28 is typical)
CRF = 23


# ------------------------------------------------------------------ #
#  Public API                                                          #
# ------------------------------------------------------------------ #

def assembleReel(recipe, output_filename):
    """
    Takes a recipe list (from recipeGenerator.buildRecipe) and renders it
    into a single vertical MP4.

    Returns (output_path, None) on success or (None, error_string) on failure.
    """
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    output_path = str(OUTPUT_FOLDER / output_filename)

    temp_dir   = tempfile.mkdtemp()
    temp_clips = []

    # --- Step 1: render each segment to a standardised temp clip --- #
    for i, segment in enumerate(recipe):
        temp_path = os.path.join(temp_dir, f"segment_{i:03d}.mp4")

        if segment["media_type"] == "video":
            ok = _renderVideoSegment(segment, temp_path)
        else:
            ok = _renderPhotoSegment(segment, temp_path)

        if not ok:
            _cleanup(temp_clips, temp_dir)
            return None, f"Failed to render segment {i} — {segment['path']}"

        temp_clips.append(temp_path)

    if not temp_clips:
        return None, "No segments were rendered."

    # --- Step 2: concatenate all segments into the final reel --- #
    ok = _concatenateClips(temp_clips, output_path)

    _cleanup(temp_clips, temp_dir)

    if not ok:
        return None, "Failed to concatenate segments into final reel."

    return output_path, None


# ------------------------------------------------------------------ #
#  Segment renderers                                                   #
# ------------------------------------------------------------------ #

def _renderVideoSegment(segment, output_path):
    """
    Trims a video to the requested window and resizes/crops to vertical format.
    Audio is normalised to stereo AAC so all clips are compatible at concat time.
    """
    cmd = [
        FFMPEG_PATH,
        "-y",
        "-ss", str(segment["start_time"]),   # seek before -i for speed
        "-i",  segment["path"],
        "-t",  str(segment["display_duration"]),
        "-vf", _scaleCropFilter(),
        "-c:v", "libx264",
        "-crf", str(CRF),
        "-preset", "fast",
        "-c:a", "aac",
        "-ar",  "44100",
        "-ac",  "2",
        # If the source has no audio, generate a silent track so concat works
        "-af",  "aresample=44100",
        output_path
    ]
    return _run(cmd)


def _renderPhotoSegment(segment, output_path):
    """
    Turns a still photo into a video clip with a slow Ken Burns zoom-in effect.
    No audio is added here; the concat step handles that.
    """
    duration = segment["display_duration"]
    fps      = PHOTO_FPS
    frames   = int(duration * fps)

    # zoompan filter: slowly zooms from 1× toward 1.5× while keeping the
    # subject centred.  We first scale way up so zoompan has pixel room,
    # then crop/scale back down to the target size.
    zoom_expr = f"min(1+{ZOOM_SPEED}*on,1.5)"
    x_expr    = "iw/2-(iw/zoom/2)"
    y_expr    = "ih/2-(ih/zoom/2)"
    zoompan   = (
        f"scale=8000:-1,"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={frames}:s={OUTPUT_WIDTH * 2}x{OUTPUT_HEIGHT * 2}:fps={fps},"
        f"{_scaleCropFilter()}"
    )

    cmd = [
        FFMPEG_PATH,
        "-y",
        "-loop",    "1",           # repeat the still image
        "-i",       segment["path"],
        "-t",       str(duration),
        "-vf",      zoompan,
        "-c:v",     "libx264",
        "-crf",     str(CRF),
        "-preset",  "fast",
        "-pix_fmt", "yuv420p",     # required for broad player compatibility
        "-an",                     # no audio — silence added during concat
        output_path
    ]
    return _run(cmd)


# ------------------------------------------------------------------ #
#  Concatenation                                                       #
# ------------------------------------------------------------------ #

def _concatenateClips(clip_paths, output_path):
    list_file    = output_path + "_concat_list.txt"
    music_track  = _pickRandomMusic()

    with open(list_file, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{clip.replace(chr(92), '/')}'\n")

    if music_track:
        cmd = [
            FFMPEG_PATH,
            "-y",
            "-f",           "concat",
            "-safe",        "0",
            "-i",           list_file,      # input 0: video (no audio)
            "-stream_loop", "-1",
            "-i",           music_track,    # input 1: music (looped)
            "-map",         "0:v",          # take video from concat
            "-map",         "1:a",          # take audio directly from music
            "-af",          f"volume={MUSIC_VOLUME}",  # adjust music volume
            "-c:v",         "libx264",
            "-crf",         str(CRF),
            "-preset",      "fast",
            "-c:a",         "aac",
            "-ar",          "44100",
            "-ac",          "2",
            "-shortest",    # stop when the video ends
            output_path
        ]
    else:
        # No music — just concat the video with no audio
        cmd = [
            FFMPEG_PATH,
            "-y",
            "-f",    "concat",
            "-safe", "0",
            "-i",    list_file,
            "-c:v",  "libx264",
            "-crf",  str(CRF),
            "-preset", "fast",
            "-an",   # no audio
            output_path
        ]

    ok = _run(cmd)

    try:
        os.remove(list_file)
    except OSError:
        pass

    return ok


# ------------------------------------------------------------------ #
#  Utilities                                                           #
# ------------------------------------------------------------------ #

def _scaleCropFilter():
    """
    ffmpeg filter chain that resizes input to fill OUTPUT_WIDTH × OUTPUT_HEIGHT
    without distortion, then centre-crops to the exact target size.
    """
    w, h = OUTPUT_WIDTH, OUTPUT_HEIGHT
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}"
    )


def _run(cmd):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Write full ffmpeg output to a debug file so we can read it
        with open("databases/ffmpeg_debug.txt", "w") as f:
            f.write("COMMAND:\n")
            f.write(" ".join(cmd) + "\n\n")
            f.write("STDOUT:\n")
            f.write(result.stdout + "\n\n")
            f.write("STDERR:\n")
            f.write(result.stderr)

        if result.returncode != 0:
            return False
        return True
    except FileNotFoundError:
        with open("databases/ffmpeg_debug.txt", "w") as f:
            f.write(f"ffmpeg not found at: {cmd[0]}")
        return False
    except Exception as e:
        with open("databases/ffmpeg_debug.txt", "w") as f:
            f.write(f"Exception: {e}")
        return False

def _cleanup(temp_clips, temp_dir):
    """Remove temporary segment files and the temp directory."""
    for path in temp_clips:
        try:
            os.remove(path)
        except OSError:
            pass
    try:
        os.rmdir(temp_dir)
    except OSError:
        pass

def _pickRandomMusic():
    """Pick a random music file from the music folder. Returns path or None."""
    if not MUSIC_FOLDER.exists():
        return None
    
    tracks = list(MUSIC_FOLDER.glob("*.mp3")) + list(MUSIC_FOLDER.glob("*.m4a"))
    
    if not tracks:
        return None
    
    return str(random.choice(tracks))