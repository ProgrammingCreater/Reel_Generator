import streamlit as st
import hashlib
import os
import subprocess
import json
import pandas as pd
import time
from pathlib import Path

from SQLHandler import SQLHandler
from recipeGenerator import buildRecipe, recipeToJson
from assembler import assembleReel, FFPROBE_PATH


# ------------------------------------------------------------------ #
#  Configuration                                                       #
# ------------------------------------------------------------------ #

PHOTO_TYPES = [".jpg", ".jpeg", ".png", ".heic"]
VIDEO_TYPES = [".mp4", ".mov", ".avi"]


# ------------------------------------------------------------------ #
#  Helper functions                                                    #
# ------------------------------------------------------------------ #

def saveFileToDisk(file, type):
    if type == "inputs":
        folder = Path("databases/inputs")
        dest = folder / file.name
    elif type == "music":
        folder = Path("databases/music")
        dest = folder / file.name

    folder.mkdir(parents=True, exist_ok=True)
    
    if not dest.exists():
        with open(dest, "wb") as f:
            f.write(file.read())
    return str(dest)


def getMediaType(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in PHOTO_TYPES:
        return "photo"
    if ext in VIDEO_TYPES:
        return "video"
    return None


def getVideoDuration(file_path):
    try:
        result = subprocess.run(
            [FFPROBE_PATH, "-v", "quiet", "-print_format", "json", "-show_format", file_path],
            capture_output=True,
            text=True
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception as e:
        st.error(f"ffprobe failed for {file_path}: {e}")
        return None


def importFile(file, db, type = "inputs"):
    path       = saveFileToDisk(file, type)
    media_id   = hashlib.md5(path.encode()).hexdigest()
    media_type = getMediaType(file.name)

    if media_type is None:
        return "skipped"

    if db.media_exists(media_id):
        return "duplicate"

    duration = getVideoDuration(path) if media_type == "video" else None

    if media_type == "video" and duration is None:
        return "skipped"

    # add_media MUST come before add_clip (foreign key constraint)
    db.add_media(media_id, path, media_type, duration)

    if media_type == "photo":
        db.add_clip(
            clip_id          = media_id + "_photo",
            media_id         = media_id,
            display_duration = 3.0
        )
    else:
        db.add_clip(
            clip_id    = media_id + "_full",
            media_id   = media_id,
            start_time = 0.0,
            end_time   = duration
        )

    return "added"


# ------------------------------------------------------------------ #
#  Database — keep one connection alive across Streamlit re-runs     #
# ------------------------------------------------------------------ #

if "db" not in st.session_state:
    st.session_state.db = SQLHandler("databases/media.db")

db = st.session_state.db


# ------------------------------------------------------------------ #
#  Page layout                                                       #
# ------------------------------------------------------------------ #

st.title("Reel Generator")


# ================================================================== #
#  SECTION 1 — Import media                                           #
# ================================================================== #

st.header("1 · Import Media")

files = st.file_uploader(
    "Upload photos and videos",
    accept_multiple_files=True,
    type=["jpg", "jpeg", "png", "mp4", "mov", "avi"]
)

if files:
    st.write(f"{len(files)} file(s) selected:")
    for f in files:
        st.write(f"  - {f.name}  ({round(f.size / 1024)} KB)")

if st.button("Submit Files"):
    if not files:
        st.warning("No files selected — upload something first.")
    else:
        added = duplicates = skipped = 0
        progress = st.progress(0)

        for i, file in enumerate(files):
            result = importFile(file, db)
            if result == "added":
                added += 1
            elif result == "duplicate":
                duplicates += 1
            else:
                skipped += 1
            progress.progress((i + 1) / len(files))

        st.success(
            f"Done — {added} imported, "
            f"{duplicates} already existed, "
            f"{skipped} skipped."
        )

# Music
musicFiles = st.file_uploader(
    "Upload music",
    accept_multiple_files=True,
    type=["mp3", "mp4"]
)

if musicFiles:
    st.write(f"{len(musicFiles)} file(s) selected:")
    for f in musicFiles:
        st.write(f"  - {f.name}  ({round(f.size / 1024)} KB)")

if st.button("Submit Music"):
    if not musicFiles:
        st.warning("No music selected — upload something first.")
    else:
        added = duplicates = skipped = 0
        progress = st.progress(0)

        for i, file in enumerate(musicFiles):
            result = importFile(file, db, "music")
            if result == "added":
                added += 1
            elif result == "duplicate":
                duplicates += 1
            else:
                skipped += 1
            progress.progress((i + 1) / len(musicFiles))

        st.success(
            f"Done — {added} imported, "
            f"{duplicates} already existed, "
            f"{skipped} skipped."
        )

if st.button("Remove Music"):
    for file in Path("databases/music").iterdir():
        if file.is_file():
            file.unlink()
    db.clear_all()
    # Reset any recipe held in session state too
    st.session_state.pop("current_recipe", None)
    st.session_state.confirm_clear = False
    st.success("Music Library cleared.")
    
# ================================================================== #
#  SECTION 2 — Media library                                          #
# ================================================================== #

st.header("2 · Media Library")

col_view, col_clear = st.columns([1, 1])

with col_view:
    if st.button("View Library"):
        rows = db.get_all_media()
        if rows:
            df = pd.DataFrame([dict(r) for r in rows])
            df = df[["path", "media_type", "duration", "date_added"]]
            df.columns = ["Path", "Type", "Duration (s)", "Date Added"]
            st.dataframe(df, use_container_width=True)
            st.write(f"Total clips in pool: **{db.clip_count()}**")
        else:
            st.info("No media imported yet.")

with col_clear:
    # Two-step confirm so the user can't accidentally wipe everything
    if st.button("Clear Library"):
        st.session_state.confirm_clear = True

if st.session_state.get("confirm_clear"):
    st.warning(
        "This will remove all media, clips, and reel history from the database. "
        "Your actual files on disk will NOT be deleted."
    )
    yes, no = st.columns(2)
    with yes:
        if st.button("Yes, clear everything"):
            for file in Path("databases/inputs").iterdir():
                if file.is_file():
                    file.unlink()
            db.clear_all()
            # Reset any recipe held in session state too
            st.session_state.pop("current_recipe", None)
            st.session_state.confirm_clear = False
            st.success("Library cleared.")
    with no:
        if st.button("Cancel"):
            st.session_state.confirm_clear = False
            st.rerun()


# ================================================================== #
#  SECTION 3 — Generate reel                                          #
# ================================================================== #

st.header("3 · Generate Reel")

use_all_photos = st.checkbox(
    "Use ALL photos in the reel",
    value=False,
    help=(
        "When checked, every photo in your library is included in the reel "
        "in a random order. The target duration setting is ignored. "
        "Uncheck to use a random selection of clips instead."
    )
)

if st.button("Build Recipe"):
    with st.spinner("Selecting clips..."):
        recipe, error = buildRecipe(db, use_all_photos=use_all_photos)

    if error:
        st.error(error)
    else:
        st.session_state.current_recipe = recipe

        total_secs = round(sum(s["display_duration"] for s in recipe), 1)
        st.success(f"Recipe ready — {len(recipe)} segments, {total_secs}s total")

        preview = []
        for s in recipe:
            filename = s["path"].replace("\\", "/").split("/")[-1]
            preview.append({
                "Type":     s["media_type"],
                "File":     filename,
                "Duration": f"{s['display_duration']}s",
                "From":     f"{s['start_time']}s" if s["start_time"] is not None else "N/A"
            })

        st.dataframe(pd.DataFrame(preview), use_container_width=True)


if st.button("Render Reel"):
    if "current_recipe" not in st.session_state:
        st.warning("Build a recipe first.")
    else:
        recipe   = st.session_state.current_recipe
        filename = f"reel_{int(time.time())}.mp4"

        with st.spinner("Rendering… this may take a minute for longer reels."):
            output_path, error = assembleReel(recipe, filename)

        if error:
            st.error(f"Render failed: {error}")
        else:
            db.save_reel(recipeToJson(recipe), output_path)
            for segment in recipe:
                db.increment_usage(segment["clip_id"])

            st.success(f"Reel saved → {output_path}")
            st.video(output_path)
            with open(output_path, "rb") as f:       # ← inside the block
                st.download_button(
                    label="Download Reel",
                    data=f,
                    file_name=filename,
                    mime="video/mp4"
                )


# ================================================================== #
#  SECTION 4 — Reel history                                           #
# ================================================================== #

st.header("4 · Reel History")

if st.button("View Past Reels"):
    reels = db.get_all_reels()
    if reels:
        for reel in reels:
            st.write(f"**#{reel['id']}** — {reel['created_time']}")
            st.write(f"Output: `{reel['output_path']}`")
            if reel["output_path"] and Path(reel["output_path"]).exists():
                st.video(reel["output_path"])
            st.divider()
    else:
        st.info("No reels generated yet.")
