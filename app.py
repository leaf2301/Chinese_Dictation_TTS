import asyncio
from datetime import datetime
import os
from pathlib import Path
import re
import signal
import threading
import time

import edge_tts
from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory
from pypinyin import Style, lazy_pinyin


app = Flask(__name__)

OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)
DICT_DIR = Path(__file__).parent / "dicts"
CEDICT_PATH = DICT_DIR / "cedict_ts.u8"
CVDICT_PATH = DICT_DIR / "CVDICT.u8"
SAVED_WORDS_FILENAME = "saved_words.txt"

IDLE_TIMEOUT_SECONDS = int(
    os.environ.get(
        "CHINESE_TTS_IDLE_MINUTES",
        "30",
    )
) * 60
last_activity_at = time.time()


VOICES = {
    "Xiaoxiao — Nữ, tự nhiên": "zh-CN-XiaoxiaoNeural",
    "Xiaoyi — Nữ, trẻ": "zh-CN-XiaoyiNeural",
    "Yunjian — Nam, trầm": "zh-CN-YunjianNeural",
    "Yunxi — Nam, trẻ": "zh-CN-YunxiNeural",
    "Yunyang — Nam, dẫn chuyện": "zh-CN-YunyangNeural",
    "Yunxia — Nam, trẻ": "zh-CN-YunxiaNeural",
}


def update_activity() -> None:
    global last_activity_at

    last_activity_at = time.time()


def parse_dictionary_file(path: Path) -> dict:
    dictionary = {}

    if not path.exists():
        return dictionary

    pattern = re.compile(
        r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+/(.*)/$"
    )

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            match = pattern.match(line)

            if not match:
                continue

            traditional, simplified, pinyin, meanings_text = (
                match.groups()
            )
            meanings = [
                meaning.strip()
                for meaning in meanings_text.split("/")
                if meaning.strip()
            ]

            if not meanings:
                continue

            entry = {
                "traditional": traditional,
                "simplified": simplified,
                "pinyin": pinyin,
                "meanings": meanings,
            }

            for key in {traditional, simplified}:
                dictionary.setdefault(key, []).append(entry)

    return dictionary


EN_DICTIONARY = parse_dictionary_file(CEDICT_PATH)
VN_DICTIONARY = parse_dictionary_file(CVDICT_PATH)


def normalize_lookup_word(word: str) -> str:
    return extract_chinese_text(word)


def summarize_meanings(
    dictionary: dict,
    word: str,
    limit: int = 4,
) -> str:
    entries = dictionary.get(word, [])

    if not entries:
        return ""

    meanings = []

    for entry in entries:
        for meaning in entry["meanings"]:
            if meaning.startswith(("CL:", "LT:")):
                continue

            if meaning in meanings:
                continue

            meanings.append(meaning)

            if len(meanings) >= limit:
                return "; ".join(meanings)

    return "; ".join(meanings)


def lookup_dictionary_word(word: str) -> dict:
    normalized_word = normalize_lookup_word(word)

    if not normalized_word:
        return {
            "word": "",
            "pinyin": "",
            "en": "",
            "vn": "",
        }

    return {
        "word": normalized_word,
        "pinyin": chinese_group_to_pinyin(
            normalized_word
        ),
        "en": summarize_meanings(
            EN_DICTIONARY,
            normalized_word,
        ),
        "vn": summarize_meanings(
            VN_DICTIONARY,
            normalized_word,
        ),
    }


def safe_output_folder_name(text: str) -> str:
    display_text = remove_markdown_marks(text)
    first_line = next(
        (
            line.strip()
            for line in display_text.splitlines()
            if line.strip()
        ),
        "Chinese TTS",
    )
    pinyin_title = chinese_group_to_pinyin(
        extract_chinese_text(first_line)
    )
    title = f"{first_line} - {pinyin_title}".strip(" -")
    title = re.sub(r"[\\/:*?\"<>|]", "-", title)
    title = re.sub(r"\s+", " ", title).strip()

    return title[:90] or "Chinese TTS"


def unique_output_folder(base_name: str) -> Path:
    timestamp = datetime.now().strftime(
        "%d-%m-%Y_%H-%M-%S"
    )
    folder = OUTPUT_DIR / f"{base_name} - {timestamp}"

    counter = 2

    while folder.exists():
        folder = OUTPUT_DIR / f"{base_name} - {timestamp}-{counter}"
        counter += 1

    folder.mkdir(parents=True)

    return folder


def get_safe_output_subfolder(folder_name: str):
    if not folder_name:
        return None

    folder = (OUTPUT_DIR / folder_name).resolve()
    output_root = OUTPUT_DIR.resolve()

    if output_root not in folder.parents:
        return None

    if not folder.is_dir():
        return None

    return folder


def format_saved_words_text(words: list) -> str:
    lines = []
    saved_index = 1

    for item in words:
        word = normalize_lookup_word(str(item.get("word", "")))

        if not word:
            continue

        en = str(item.get("en", "")).strip()
        vn = str(item.get("vn", "")).strip()
        pinyin = str(item.get("pinyin", "")).strip()

        lines.append(
            f"{saved_index}. {word} - {pinyin}\n"
            f"   EN: {en}\n"
            f"   VN: {vn}"
        )
        saved_index += 1

    return "\n\n".join(lines) + ("\n" if lines else "")


def idle_shutdown_watchdog() -> None:
    while True:
        time.sleep(60)

        if time.time() - last_activity_at < IDLE_TIMEOUT_SECONDS:
            continue

        print("Idle timeout reached. Shutting down Chinese TTS.")
        os.kill(os.getpid(), signal.SIGTERM)


@app.before_request
def mark_activity():
    update_activity()


HTML_PAGE = """
<!doctype html>
<html lang="vi">
<head>
    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <title>Chinese TTS</title>

    <style>
        * {
            box-sizing: border-box;
        }

        body {
            max-width: 1000px;
            margin: 30px auto;
            padding: 0 20px 150px;
            font-family:
                Arial,
                "PingFang SC",
                "Microsoft YaHei",
                sans-serif;
        }

        h1,
        h2 {
            margin-bottom: 16px;
        }

        textarea {
            width: 100%;
            min-height: 220px;
            padding: 12px;
            border: 1px solid #aaa;
            border-radius: 6px;
            resize: vertical;
            font-size: 20px;
            line-height: 1.6;
            font-family:
                "PingFang SC",
                "Microsoft YaHei",
                sans-serif;
        }

        select,
        button {
            padding: 9px 14px;
            border: 1px solid #999;
            border-radius: 5px;
            background: white;
            font-size: 15px;
        }

        button {
            cursor: pointer;
        }

        button:hover {
            background: #f0f0f0;
        }

        .form-row {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            margin-top: 16px;
        }

        .generate-button {
            font-weight: bold;
        }

        .source-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 18px;
        }

        .source-field {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .error {
            padding: 10px 12px;
            border: 1px solid #d33;
            border-radius: 5px;
            color: #b00020;
            background: #fff5f5;
        }

        .reading-section,
        .writing-section {
            margin-top: 32px;
            padding-top: 24px;
            border-top: 1px solid #ddd;
        }

        .audio-section {
            position: fixed;
            right: 0;
            bottom: 0;
            left: 0;
            z-index: 20;
            padding: 14px 20px;
            border-top: 1px solid #ddd;
            background: rgba(255, 255, 255, 0.96);
            box-shadow: 0 -8px 22px rgba(0, 0, 0, 0.12);
            backdrop-filter: blur(10px);
        }

        .audio-player-bar {
            display: grid;
            grid-template-columns: auto 1fr auto;
            align-items: center;
            gap: 14px;
            max-width: 1000px;
            margin: 0 auto;
        }

        .player-center {
            min-width: 0;
        }

        .audio-controls {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }

        .play-button {
            min-width: 86px;
            border-color: #222;
            background: #222;
            color: white;
            font-weight: bold;
        }

        .play-button:hover {
            background: #444;
        }

        .seek-control {
            display: inline-flex;
            align-items: center;
            overflow: hidden;
            border: 1px solid #999;
            border-radius: 8px;
            background: white;
        }

        .seek-main-button {
            min-width: 82px;
            border-width: 0 1px;
            border-radius: 0;
        }

        .seek-adjust {
            display: contents;
        }

        .seek-adjust-button {
            width: 42px;
            min-width: 42px;
            padding: 9px 0;
            border: 0;
            border-radius: 0;
            font-size: 14px;
            line-height: 1.2;
        }

        .time-display {
            min-width: 120px;
            font-family: monospace;
            font-size: 15px;
        }

        .progress-bar {
            width: 100%;
            cursor: pointer;
        }

        .download-link {
            display: inline-block;
            white-space: nowrap;
        }

        .reading-track-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 18px;
        }

        .reading-field {
            display: flex;
            min-width: 0;
            flex-direction: column;
            gap: 12px;
        }

        .reading-card {
            height: 220px;
            padding: 12px;
            border: 1px solid #aaa;
            border-radius: 6px;
            background: white;
            overflow-y: auto;
            user-select: text;
            font-family:
                "PingFang SC",
                "Microsoft YaHei",
                sans-serif;
        }

        .current-chinese {
            margin: 0;
            font-size: 34px;
            line-height: 1.6;
            overflow-wrap: anywhere;
        }

        .current-pinyin {
            margin: 0;
            color: #444;
            font-size: 21px;
            line-height: 1.6;
            overflow-wrap: anywhere;
        }

        .reading-token {
            display: inline;
            border-radius: 5px;
            transition:
                background-color 0.16s ease,
                color 0.16s ease;
        }

        .reading-token.active {
            background: #ffeb70;
            color: #111;
            box-shadow: 0 0 0 3px #ffeb70;
        }

        .save-selection-menu {
            position: fixed;
            z-index: 40;
            display: none;
            width: min(340px, calc(100vw - 24px));
            padding: 10px;
            border: 1px solid #999;
            border-radius: 6px;
            background: white;
            box-shadow: 0 6px 18px rgba(0, 0, 0, 0.16);
        }

        .save-selection-menu.is-visible {
            display: block;
        }

        .lookup-word {
            margin: 0 0 6px;
            font-weight: bold;
        }

        .lookup-line {
            margin: 4px 0;
            color: #333;
            font-size: 14px;
            line-height: 1.45;
        }

        .save-selection-menu button {
            width: 100%;
            margin-top: 8px;
        }

        .saved-words-panel {
            position: fixed;
            right: 18px;
            bottom: 96px;
            z-index: 35;
            display: none;
            width: min(240px, calc(100vw - 36px));
            max-height: min(760px, calc(100vh - 132px));
            padding: 12px;
            border: 1px solid #999;
            border-radius: 6px;
            background: white;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
        }

        .saved-words-panel.is-visible {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .saved-words-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            font-weight: bold;
        }

        .saved-words-close {
            width: 28px;
            height: 28px;
            min-width: 28px;
            padding: 0;
            border-radius: 50%;
            font-size: 18px;
            line-height: 1;
        }

        .saved-words-list {
            max-height: min(580px, calc(100vh - 290px));
            margin: 0;
            padding-left: 24px;
            overflow-y: auto;
            color: #222;
            font-size: 14px;
            line-height: 1.5;
        }

        .saved-words-list li {
            margin-bottom: 8px;
        }

        .saved-word-meta {
            display: block;
            color: #555;
        }

        .save-status {
            min-height: 18px;
            margin: 0;
            color: #555;
            font-size: 13px;
        }

        .saved-words-chip {
            position: fixed;
            right: 18px;
            bottom: 96px;
            z-index: 35;
            display: none;
            width: 54px;
            height: 54px;
            padding: 0;
            border: 1px solid #999;
            border-radius: 50%;
            background: white;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
            font-weight: bold;
        }

        .saved-words-chip.is-visible {
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }

        .character-grid {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 7px;
            margin-top: 18px;
        }

        .character-input {
            width: 46px;
            height: 46px;
            padding: 0;
            border: 1px solid #999;
            border-radius: 5px;
            text-align: center;
            font-size: 27px;
            line-height: 46px;
            font-family:
                "PingFang SC",
                "Microsoft YaHei",
                "Noto Sans CJK SC",
                sans-serif;
        }

        .character-input:focus {
            border-color: #222;
            outline: 2px solid #555;
            outline-offset: 1px;
        }

        .character-input.correct {
            border-color: #16823a;
            background: #f1fff5;
        }

        .character-input.incorrect {
            border-color: #c62828;
            background: #fff1f1;
        }

        .character-input:disabled {
            color: #222;
            opacity: 1;
        }

        .punctuation {
            display: inline-flex;
            align-items: flex-end;
            justify-content: center;
            min-width: 14px;
            height: 46px;
            font-size: 27px;
            line-height: 46px;
        }

        .text-space {
            display: inline-block;
            width: 14px;
        }

        .line-break {
            flex-basis: 100%;
            height: 0;
        }

        .instructions {
            color: #555;
            line-height: 1.6;
        }

        .check-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin-top: 24px;
        }

        .check-button {
            font-weight: bold;
        }

        .replay-button {
            border-color: #555;
        }

        .check-result {
            margin-top: 18px;
            padding: 16px;
            border: 1px solid #c8c8c8;
            border-radius: 6px;
            background: #fcfcfc;
        }

        .check-summary {
            margin: 0 0 12px;
            font-weight: bold;
        }

        .check-legend {
            margin: 0 0 12px;
            color: #555;
            font-size: 14px;
            line-height: 1.5;
        }

        .check-diff {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            font-size: 24px;
            line-height: 1.8;
        }

        .check-group {
            display: inline-flex;
            gap: 5px;
        }

        .diff-char {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 30px;
            min-height: 34px;
            padding: 0 4px;
            border: 1px solid transparent;
            border-radius: 6px;
        }

        .diff-correct {
            color: #1e3a8a;
            background: #dbeafe;
            border-color: #2563eb;
        }

        .diff-missing {
            color: rgba(31, 41, 51, 0.32);
            background: white;
            border-color: #d1d5db;
        }

        .diff-extra {
            color: #7f1d1d;
            background: #fecaca;
            border-color: #dc2626;
            opacity: 1;
        }

        .diff-punctuation {
            color: #1f2933;
            border-color: transparent;
            background: transparent;
        }

        @media (max-width: 760px) {
            .source-grid,
            .reading-track-grid {
                grid-template-columns: 1fr;
            }

            .audio-player-bar {
                grid-template-columns: 1fr;
                gap: 10px;
            }

            .audio-controls {
                justify-content: center;
            }

            .download-link {
                margin-left: 0;
            }
        }
    </style>
</head>

<body>
    <h1>Chinese Text to Speech</h1>

    {% if error %}
        <p class="error">
            {{ error }}
        </p>
    {% endif %}

    <form method="post">
        <div class="source-grid">
            <div class="source-field">
                <label for="text">
                    <strong>Văn bản tiếng Trung đã tách cụm</strong>
                </label>

                <textarea
                    id="text"
                    name="text"
                    placeholder="今天 是 星期天，我 不用 上班，也 不用 早起。"
                    required
                >{{ text }}</textarea>
            </div>
        </div>

        <div class="form-row">
            <label for="voice">
                <strong>Giọng đọc:</strong>
            </label>

            <select id="voice" name="voice">
                {% for label, voice_id in voices.items() %}
                    <option
                        value="{{ voice_id }}"
                        {% if voice_id == selected_voice %}
                            selected
                        {% endif %}
                    >
                        {{ label }}
                    </option>
                {% endfor %}
            </select>

            <button
                class="generate-button"
                type="submit"
            >
                Tạo MP3
            </button>
        </div>
    </form>

    {% if audio_url %}
        <section class="reading-section">
            <h2>Đoạn đang đọc</h2>

            <div class="reading-track-grid">
                <div class="reading-field">
                    <label for="currentChinese">
                        <strong>Tiếng Trung</strong>
                    </label>

                    <div
                        class="reading-card"
                    >
                        <p
                            id="currentChinese"
                            class="current-chinese"
                        ></p>
                    </div>
                </div>

                <div class="reading-field">
                    <label for="currentPinyin">
                        <strong>Pinyin</strong>
                    </label>

                    <div
                        class="reading-card"
                    >
                        <p
                            id="currentPinyin"
                            class="current-pinyin"
                        ></p>
                    </div>
                </div>
            </div>
        </section>

        <section class="audio-section">
            <div class="audio-player-bar">
                <audio
                    id="audioPlayer"
                    preload="metadata"
                    src="{{ audio_url }}"
                ></audio>

                <div class="audio-controls">
                    <div class="seek-control">
                        <button
                            class="seek-adjust-button seek-decrease-button"
                            type="button"
                            data-seek-target="backward"
                            aria-label="Giảm số giây lùi hoặc tới"
                        >
                            −
                        </button>

                        <button
                            id="backwardButton"
                            class="seek-main-button"
                            type="button"
                        >
                            −3 giây
                        </button>

                        <button
                            class="seek-adjust-button seek-increase-button"
                            type="button"
                            data-seek-target="backward"
                            aria-label="Tăng số giây lùi hoặc tới"
                        >
                            +
                        </button>
                    </div>

                    <button
                        id="playButton"
                        class="play-button"
                        type="button"
                    >
                        Phát
                    </button>

                    <div class="seek-control">
                        <button
                            class="seek-adjust-button seek-decrease-button"
                            type="button"
                            data-seek-target="forward"
                            aria-label="Giảm số giây lùi hoặc tới"
                        >
                            −
                        </button>

                        <button
                            id="forwardButton"
                            class="seek-main-button"
                            type="button"
                        >
                            +5 giây
                        </button>

                        <button
                            class="seek-adjust-button seek-increase-button"
                            type="button"
                            data-seek-target="forward"
                            aria-label="Tăng số giây lùi hoặc tới"
                        >
                            +
                        </button>
                    </div>
                </div>

                <div class="player-center">
                    <input
                        id="progressBar"
                        class="progress-bar"
                        type="range"
                        min="0"
                        max="100"
                        value="0"
                        step="0.1"
                    >

                    <span
                        id="timeDisplay"
                        class="time-display"
                    >
                        00:00 / 00:00
                    </span>
                </div>

                <div class="audio-controls">
                    <label for="playbackRate">
                        Tốc độ:
                    </label>

                    <select id="playbackRate">
                        <option value="0.5">0.5x</option>
                        <option value="0.75">0.75x</option>
                        <option value="1" selected>1x</option>
                        <option value="1.25">1.25x</option>
                        <option value="1.5">1.5x</option>
                        <option value="2">2x</option>
                    </select>

                </div>
            </div>
        </section>

        <section class="writing-section">
            <h2>Nhập lại chữ Trung</h2>

            <p class="instructions">
                Gõ hoặc dán nhiều chữ vào bất kỳ ô nào,
                các chữ sẽ tự động điền sang những ô tiếp theo.
                Dấu câu được hiển thị sẵn.
            </p>

            <p class="instructions">
                Space: phát hoặc tạm dừng audio.
                Backspace: xóa chữ hiện tại;
                nếu ô trống thì quay về và xóa ô trước.
            </p>

            <div
                id="characterGrid"
                class="character-grid"
            >
                {% set input_index = namespace(value=0) %}

                {% for item in character_items %}
                    {% if item.type == "input" %}
                        <input
                            class="character-input"
                            type="text"
                            inputmode="text"
                            autocomplete="off"
                            autocorrect="off"
                            autocapitalize="off"
                            spellcheck="false"
                            data-input-index="{{ input_index.value }}"
                            data-check-segment="{{ item.check_segment }}"
                            data-expected-character="{{ item.character }}"
                            aria-label="Ô chữ số {{ input_index.value + 1 }}"
                        >

                        {% set input_index.value =
                            input_index.value + 1 %}

                    {% elif item.type == "punctuation" %}
                        <span
                            class="punctuation"
                            data-ends-check-segment="{{ 'true' if item.ends_check_segment else 'false' }}"
                        >
                            {{ item.character }}
                        </span>

                    {% elif item.type == "space" %}
                        <span class="text-space"></span>

                    {% elif item.type == "line_break" %}
                        <span class="line-break"></span>
                    {% endif %}
                {% endfor %}
            </div>

            <div class="check-actions">
                <button
                    id="checkWritingButton"
                    class="check-button"
                    type="button"
                >
                    Check bài viết
                </button>

                <button
                    id="replayWritingButton"
                    class="replay-button"
                    type="button"
                    hidden
                >
                    Làm lại
                </button>
            </div>

            <div
                id="checkResult"
                class="check-result"
                hidden
            >
                <p
                    id="checkSummary"
                    class="check-summary"
                ></p>

                <p class="check-legend">
                    Xanh dương: đúng. Đỏ: sai. Chữ mờ: thiếu.
                </p>

                <div
                    id="checkDiff"
                    class="check-diff"
                ></div>
            </div>
        </section>

        <div
            id="saveSelectionMenu"
            class="save-selection-menu"
        >
            <p
                id="lookupWord"
                class="lookup-word"
            ></p>

            <p
                id="lookupEnglish"
                class="lookup-line"
            ></p>

            <p
                id="lookupVietnamese"
                class="lookup-line"
            ></p>

            <button
                id="saveSelectionButton"
                type="button"
            >
                Save
            </button>
        </div>

        <aside
            id="savedWordsPanel"
            class="saved-words-panel"
        >
            <div class="saved-words-header">
                <span id="savedWordsCount">
                    Đã lưu: 0
                </span>

                <button
                    id="closeSavedWordsButton"
                    class="saved-words-close"
                    type="button"
                    aria-label="Ẩn danh sách đã lưu"
                >
                    ×
                </button>
            </div>

            <ol
                id="savedWordsList"
                class="saved-words-list"
            ></ol>

            <button
                id="downloadSavedWordsButton"
                type="button"
            >
                Download TXT
            </button>

            <p
                id="saveWordsStatus"
                class="save-status"
            ></p>
        </aside>

        <button
            id="savedWordsChip"
            class="saved-words-chip"
            type="button"
            aria-label="Hiện danh sách đã lưu"
        >
            0
        </button>
    {% endif %}


    <script>
        const readingSegments =
            {{ reading_segments | tojson }};

        const targetCharacters =
            {{ target_characters | tojson }};

        const checkGroups =
            {{ check_groups | tojson }};

        const checkSegments =
            {{ check_segments | tojson }};

        const outputFolder =
            {{ output_folder | tojson }};

        const sourceForm =
            document.querySelector("form");

        const generateButton =
            document.querySelector(".generate-button");

        if (sourceForm && generateButton) {
            sourceForm.addEventListener(
                "submit",
                () => {
                    generateButton.disabled = true;
                    generateButton.textContent = "Đang tạo MP3...";
                }
            );
        }

        function pingServerActivity() {
            fetch(
                "/ping",
                {
                    method: "POST",
                    keepalive: true,
                }
            ).catch(() => {});
        }

        pingServerActivity();
        setInterval(pingServerActivity, 5 * 60 * 1000);

        /*
         * AUDIO PLAYER
         */

        const audio = document.getElementById("audioPlayer");

        if (audio) {
            const playButton =
                document.getElementById("playButton");

            const backwardButton =
                document.getElementById("backwardButton");

            const forwardButton =
                document.getElementById("forwardButton");

            const playbackRate =
                document.getElementById("playbackRate");

            const progressBar =
                document.getElementById("progressBar");

            const timeDisplay =
                document.getElementById("timeDisplay");

            const currentChinese =
                document.getElementById("currentChinese");

            const currentPinyin =
                document.getElementById("currentPinyin");

            const seekDecreaseButtons = Array.from(
                document.querySelectorAll(
                    ".seek-decrease-button"
                )
            );

            const seekIncreaseButtons = Array.from(
                document.querySelectorAll(
                    ".seek-increase-button"
                )
            );

            let backwardSeconds = 3;
            let forwardSeconds = 5;
            const minSeekSeconds = 3;
            const maxSeekSeconds = 15;
            let activeChineseTokenKey = "";
            let activePinyinTokenKey = "";


            function formatTime(seconds) {
                if (!Number.isFinite(seconds)) {
                    return "00:00";
                }

                const minutes = Math.floor(seconds / 60);
                const remainingSeconds =
                    Math.floor(seconds % 60);

                return (
                    String(minutes).padStart(2, "0")
                    + ":"
                    + String(remainingSeconds).padStart(2, "0")
                );
            }


            function updateAudioDisplay() {
                const duration = audio.duration;

                timeDisplay.textContent =
                    formatTime(audio.currentTime)
                    + " / "
                    + formatTime(duration);

                if (
                    Number.isFinite(duration)
                    && duration > 0
                ) {
                    progressBar.value =
                        (audio.currentTime / duration) * 100;
                }
            }


            function getReadingTokens() {
                return readingSegments.flatMap(
                    (segment, segmentIndex) => {
                        const tokens = segment.tokens || [
                            {
                                chinese: segment.chinese,
                                pinyin: segment.pinyin,
                                weight: segment.weight,
                            },
                        ];

                        return tokens.map(
                            (token, tokenIndex) => ({
                                ...token,
                                segmentIndex,
                                tokenIndex,
                                key: (
                                    segmentIndex
                                    + "-"
                                    + tokenIndex
                                ),
                                weight: Math.max(
                                    Number(token.weight) || 1,
                                    1
                                ),
                            })
                        );
                    }
                );
            }


            function getPinyinTokens() {
                return readingSegments.flatMap(
                    (segment, segmentIndex) => {
                        const tokens =
                            segment.pinyin_tokens || [];

                        return tokens.map(
                            (token, tokenIndex) => ({
                                ...token,
                                segmentIndex,
                                tokenIndex,
                                key: (
                                    "p-"
                                    + segmentIndex
                                    + "-"
                                    + tokenIndex
                                ),
                                weight: Math.max(
                                    Number(token.weight) || 1,
                                    1
                                ),
                            })
                        );
                    }
                );
            }


            const readingTokens = getReadingTokens();
            const pinyinTokens = getPinyinTokens();


            function renderReadingTrack() {
                if (readingSegments.length === 0) {
                    currentChinese.textContent =
                        "Chưa có dữ liệu để hiển thị.";
                    currentPinyin.textContent = "";
                    return;
                }

                currentChinese.textContent = "";
                currentPinyin.textContent = "";

                readingSegments.forEach(
                    (segment, segmentIndex) => {
                        const tokens = segment.tokens || [
                            {
                                chinese: segment.chinese,
                            },
                        ];
                        const pinyinTokensForSegment =
                            segment.pinyin_tokens || [];

                        if (segmentIndex > 0) {
                            currentChinese.appendChild(
                                document.createElement("br")
                            );
                            currentPinyin.appendChild(
                                document.createElement("br")
                            );
                        }

                        tokens.forEach((token, tokenIndex) => {
                            const key =
                                segmentIndex + "-" + tokenIndex;
                            const matchingPinyin =
                                pinyinTokensForSegment[tokenIndex];

                            const chineseToken =
                                document.createElement("span");
                            chineseToken.className =
                                "reading-token";
                            chineseToken.dataset.tokenKey = key;
                            chineseToken.dataset.saveChinese =
                                token.chinese || "";
                            chineseToken.dataset.savePinyin =
                                matchingPinyin?.pinyin || "";
                            chineseToken.textContent =
                                token.chinese;
                            currentChinese.appendChild(
                                chineseToken
                            );

                            if (tokenIndex < tokens.length - 1) {
                                currentChinese.appendChild(
                                    document.createTextNode(" ")
                                );
                            }
                        });

                        pinyinTokensForSegment.forEach(
                            (token, tokenIndex) => {
                                const key =
                                    "p-"
                                    + segmentIndex
                                    + "-"
                                    + tokenIndex;

                                const pinyinToken =
                                    document.createElement("span");
                                pinyinToken.className =
                                    "reading-token";
                                pinyinToken.dataset.pinyinTokenKey =
                                    key;
                                pinyinToken.dataset.saveChinese =
                                    tokens[tokenIndex]?.chinese || "";
                                pinyinToken.dataset.savePinyin =
                                    token.pinyin || "";
                                pinyinToken.textContent =
                                    token.pinyin || "";
                                currentPinyin.appendChild(
                                    pinyinToken
                                );

                                if (
                                    tokenIndex
                                    < pinyinTokensForSegment.length - 1
                                ) {
                                    currentPinyin.appendChild(
                                        document.createTextNode(" ")
                                    );
                                }
                            }
                        );
                    }
                );
            }


            function getCurrentToken(tokens) {
                if (tokens.length === 0) {
                    return null;
                }

                const timedTokens = tokens.filter(
                    token => Number.isFinite(token.start)
                );

                if (timedTokens.length > 0) {
                    const currentTime = audio.currentTime;

                    if (currentTime <= timedTokens[0].start) {
                        return timedTokens[0];
                    }

                    for (
                        let index = 0;
                        index < timedTokens.length;
                        index += 1
                    ) {
                        const token = timedTokens[index];
                        const nextToken =
                            timedTokens[index + 1];
                        const tokenEnd =
                            Number.isFinite(token.end)
                                ? token.end
                                : nextToken?.start;

                        if (
                            nextToken
                            && currentTime >= token.start
                            && currentTime < nextToken.start
                        ) {
                            return token;
                        }

                        if (
                            !nextToken
                            && (
                                currentTime >= token.start
                                || currentTime <= tokenEnd
                            )
                        ) {
                            return token;
                        }
                    }

                    return timedTokens[timedTokens.length - 1];
                }

                const duration = audio.duration;

                if (
                    !Number.isFinite(duration)
                    || duration <= 0
                ) {
                    return tokens[0];
                }

                const totalWeight = tokens.reduce(
                    (total, token) => (
                        total + token.weight
                    ),
                    0
                );

                const currentWeight =
                    (audio.currentTime / duration)
                    * totalWeight;

                let accumulatedWeight = 0;

                for (const token of tokens) {
                    accumulatedWeight += token.weight;

                    if (
                        currentWeight <= accumulatedWeight
                    ) {
                        return token;
                    }
                }

                return tokens[tokens.length - 1];
            }


            function scrollTokenIntoView(element) {
                const card = element.closest(".reading-card");

                if (!card) {
                    return;
                }

                const cardRect = card.getBoundingClientRect();
                const tokenRect = element.getBoundingClientRect();
                const padding = 24;

                if (
                    tokenRect.top >= cardRect.top + padding
                    && tokenRect.bottom <= cardRect.bottom - padding
                ) {
                    return;
                }

                const targetScrollTop =
                    card.scrollTop
                    + tokenRect.top
                    - cardRect.top
                    - (card.clientHeight / 2)
                    + (tokenRect.height / 2);

                card.scrollTo({
                    top: Math.max(0, targetScrollTop),
                    behavior: audio.paused ? "auto" : "smooth",
                });
            }


            function updateCurrentReading() {
                const chineseToken =
                    getCurrentToken(readingTokens);
                const pinyinToken =
                    getCurrentToken(pinyinTokens);

                if (
                    chineseToken
                    && chineseToken.key !== activeChineseTokenKey
                ) {
                    activeChineseTokenKey = chineseToken.key;

                    currentChinese
                        .querySelectorAll(".reading-token.active")
                        .forEach(element => {
                            element.classList.remove("active");
                        });

                    currentChinese
                        .querySelectorAll(
                            '[data-token-key="'
                            + chineseToken.key
                            + '"]'
                        )
                        .forEach(element => {
                            element.classList.add("active");
                            scrollTokenIntoView(element);
                        });
                }

                if (
                    pinyinToken
                    && pinyinToken.key !== activePinyinTokenKey
                ) {
                    activePinyinTokenKey = pinyinToken.key;

                    currentPinyin
                        .querySelectorAll(".reading-token.active")
                        .forEach(element => {
                            element.classList.remove("active");
                        });

                    currentPinyin
                        .querySelectorAll(
                            '[data-pinyin-token-key="'
                            + pinyinToken.key
                            + '"]'
                        )
                        .forEach(element => {
                            element.classList.add("active");
                            scrollTokenIntoView(element);
                        });
                }
            }


            function updateSeekButtons() {
                backwardButton.textContent =
                    "−" + backwardSeconds + " giây";

                forwardButton.textContent =
                    "+" + forwardSeconds + " giây";
            }


            function adjustSeekSeconds(target, delta) {
                if (target === "backward") {
                    backwardSeconds = Math.min(
                        maxSeekSeconds,
                        Math.max(
                            minSeekSeconds,
                            backwardSeconds + delta
                        )
                    );
                }

                if (target === "forward") {
                    forwardSeconds = Math.min(
                        maxSeekSeconds,
                        Math.max(
                            minSeekSeconds,
                            forwardSeconds + delta
                        )
                    );
                }

                updateSeekButtons();
            }


            function getSeekTarget(button) {
                return button.dataset.seekTarget || "forward";
            }


            function getSeekDelta(button) {
                return button.classList.contains(
                    "seek-decrease-button"
                )
                    ? -1
                    : 1;
            }


            async function toggleAudioPlayback() {
                if (audio.paused) {
                    try {
                        await audio.play();
                    } catch (error) {
                        console.error(
                            "Không thể phát audio:",
                            error
                        );
                    }
                } else {
                    audio.pause();
                }
            }


            function isTypingTarget(element) {
                if (!element) {
                    return false;
                }

                if (
                    element.classList
                    && element.classList.contains(
                        "character-input"
                    )
                ) {
                    return false;
                }

                const tagName = element.tagName;

                return (
                    element.isContentEditable
                    || tagName === "INPUT"
                    || tagName === "TEXTAREA"
                    || tagName === "SELECT"
                    || tagName === "BUTTON"
                );
            }


            playButton.addEventListener(
                "click",
                toggleAudioPlayback
            );


            function seekBackward() {
                audio.currentTime = Math.max(
                    0,
                    audio.currentTime - backwardSeconds
                );
            }


            function seekForward() {
                const duration =
                    Number.isFinite(audio.duration)
                        ? audio.duration
                        : audio.currentTime + forwardSeconds;

                audio.currentTime = Math.min(
                    duration,
                    audio.currentTime + forwardSeconds
                );
            }


            document.addEventListener(
                "keydown",
                event => {
                    if (isTypingTarget(document.activeElement)) {
                        return;
                    }

                    if (event.key === " ") {
                        event.preventDefault();
                        toggleAudioPlayback();
                    }

                    if (event.key === "ArrowLeft") {
                        event.preventDefault();
                        seekBackward();
                    }

                    if (event.key === "ArrowRight") {
                        event.preventDefault();
                        seekForward();
                    }
                }
            );


            audio.addEventListener("play", () => {
                playButton.textContent = "Tạm dừng";
            });


            audio.addEventListener("pause", () => {
                playButton.textContent = "Phát";
            });


            audio.addEventListener("ended", () => {
                playButton.textContent = "Phát";
            });


            backwardButton.addEventListener(
                "click",
                seekBackward
            );


            forwardButton.addEventListener(
                "click",
                seekForward
            );


            seekDecreaseButtons.forEach(button => {
                button.addEventListener(
                    "click",
                    () => {
                        adjustSeekSeconds(
                            getSeekTarget(button),
                            getSeekDelta(button)
                        );
                    }
                );
            });


            seekIncreaseButtons.forEach(button => {
                button.addEventListener(
                    "click",
                    () => {
                        adjustSeekSeconds(
                            getSeekTarget(button),
                            getSeekDelta(button)
                        );
                    }
                );
            });


            playbackRate.addEventListener(
                "change",
                () => {
                    audio.playbackRate =
                        Number(playbackRate.value);
                }
            );


            audio.addEventListener(
                "loadedmetadata",
                updateAudioDisplay
            );


            audio.addEventListener(
                "timeupdate",
                () => {
                    updateAudioDisplay();
                    updateCurrentReading();
                }
            );


            progressBar.addEventListener(
                "input",
                () => {
                    if (
                        !Number.isFinite(audio.duration)
                        || audio.duration <= 0
                    ) {
                        return;
                    }

                    audio.currentTime =
                        (
                            Number(progressBar.value)
                            / 100
                        )
                        * audio.duration;

                    updateCurrentReading();
                }
            );


            renderReadingTrack();
            updateCurrentReading();
        }


        /*
         * CHARACTER INPUTS
         */

        const characterInputs = Array.from(
            document.querySelectorAll(".character-input")
        );

        const checkWritingButton =
            document.getElementById("checkWritingButton");

        const replayWritingButton =
            document.getElementById("replayWritingButton");

        const checkResult =
            document.getElementById("checkResult");

        const checkSummary =
            document.getElementById("checkSummary");

        const checkDiff =
            document.getElementById("checkDiff");

        const saveSelectionMenu =
            document.getElementById("saveSelectionMenu");

        const saveSelectionButton =
            document.getElementById("saveSelectionButton");

        const lookupWord =
            document.getElementById("lookupWord");

        const lookupEnglish =
            document.getElementById("lookupEnglish");

        const lookupVietnamese =
            document.getElementById("lookupVietnamese");

        const savedWordsPanel =
            document.getElementById("savedWordsPanel");

        const savedWordsCount =
            document.getElementById("savedWordsCount");

        const savedWordsList =
            document.getElementById("savedWordsList");

        const closeSavedWordsButton =
            document.getElementById("closeSavedWordsButton");

        const savedWordsChip =
            document.getElementById("savedWordsChip");

        const downloadSavedWordsButton =
            document.getElementById("downloadSavedWordsButton");

        const saveWordsStatus =
            document.getElementById("saveWordsStatus");

        let isDistributingText = false;
        let pendingLookupEntry = null;
        let isLookupLoading = false;
        let isSavedWordsPanelOpen = false;
        const savedWords = [];


        function splitCharacters(value) {
            return Array.from(value).filter(
                character => !/\\s/.test(character)
            );
        }


        function hideSaveSelectionMenu() {
            if (!saveSelectionMenu) {
                return;
            }

            saveSelectionMenu.classList.remove("is-visible");

            if (!isLookupLoading && saveSelectionButton) {
                saveSelectionButton.disabled = false;
            }
        }


        function isDictionaryUiTarget(target) {
            return Boolean(
                (
                    saveSelectionMenu
                    && saveSelectionMenu.contains(target)
                )
                || (
                    savedWordsPanel
                    && savedWordsPanel.contains(target)
                )
                || (
                    savedWordsChip
                    && savedWordsChip.contains(target)
                )
            );
        }


        function getChineseLookupText(value) {
            return Array.from(value || "")
                .filter(character => (
                    /[\\u3400-\\u4dbf\\u4e00-\\u9fff]/.test(character)
                ))
                .join("");
        }


        function getLookupTextFromElement(element) {
            if (!element) {
                return "";
            }

            const input =
                element.closest(".character-input");

            if (input) {
                return getChineseLookupText(
                    input.value
                    || input.dataset.expectedCharacter
                    || ""
                );
            }

            const token =
                element.closest(".reading-token");

            if (token) {
                return getChineseLookupText(
                    token.dataset.saveChinese
                    || token.textContent
                    || ""
                );
            }

            const diffChar =
                element.closest(".diff-char");

            if (diffChar) {
                return getChineseLookupText(
                    diffChar.textContent || ""
                );
            }

            return "";
        }


        function positionLookupMenu(x, y) {
            if (!saveSelectionMenu) {
                return;
            }

            const margin = 10;
            const rect =
                saveSelectionMenu.getBoundingClientRect();
            const left =
                Math.min(
                    x,
                    window.innerWidth - rect.width - margin
                );
            const top =
                Math.min(
                    y,
                    window.innerHeight - rect.height - margin
                );

            saveSelectionMenu.style.left =
                Math.max(margin, left) + "px";
            saveSelectionMenu.style.top =
                Math.max(margin, top) + "px";
        }


        async function showLookupMenu(word, x, y) {
            const normalizedWord =
                getChineseLookupText(word);

            if (
                !normalizedWord
                || !saveSelectionMenu
                || !lookupWord
                || !lookupEnglish
                || !lookupVietnamese
            ) {
                hideSaveSelectionMenu();
                return;
            }

            pendingLookupEntry = {
                word: normalizedWord,
                pinyin: "",
                en: "",
                vn: "",
            };
            isLookupLoading = true;

            if (saveSelectionButton) {
                saveSelectionButton.disabled = true;
            }

            lookupWord.textContent =
                normalizedWord;
            lookupEnglish.textContent =
                "EN: Đang tra...";
            lookupVietnamese.textContent =
                "VN: Đang tra...";
            saveSelectionMenu.classList.add(
                "is-visible"
            );
            positionLookupMenu(x, y);

            try {
                const response = await fetch(
                    "/lookup?word="
                    + encodeURIComponent(normalizedWord)
                );

                if (!response.ok) {
                    throw new Error("Lookup failed");
                }

                const entry = await response.json();
                pendingLookupEntry = {
                    word: entry.word || normalizedWord,
                    pinyin: entry.pinyin || "",
                    en: entry.en || "",
                    vn: entry.vn || "",
                };
                lookupWord.textContent =
                    pendingLookupEntry.word
                    + (
                        pendingLookupEntry.pinyin
                            ? " - " + pendingLookupEntry.pinyin
                            : ""
                    );
                lookupEnglish.textContent =
                    "EN: " + (
                        pendingLookupEntry.en || "Không tìm thấy"
                    );
                lookupVietnamese.textContent =
                    "VN: " + (
                        pendingLookupEntry.vn || "Không tìm thấy"
                    );
                positionLookupMenu(x, y);

            } catch (error) {
                lookupEnglish.textContent =
                    "EN: Không tra được";
                lookupVietnamese.textContent =
                    "VN: Không tra được";

            } finally {
                isLookupLoading = false;

                if (saveSelectionButton) {
                    saveSelectionButton.disabled = false;
                }
            }
        }


        function renderSavedWordsPanel() {
            if (
                !savedWordsPanel
                || !savedWordsCount
                || !savedWordsList
            ) {
                return;
            }

            savedWordsPanel.classList.toggle(
                "is-visible",
                savedWords.length > 0
                && isSavedWordsPanelOpen
            );

            if (savedWordsChip) {
                savedWordsChip.classList.toggle(
                    "is-visible",
                    savedWords.length > 0
                    && !isSavedWordsPanelOpen
                );
                savedWordsChip.textContent =
                    String(savedWords.length);
            }

            savedWordsCount.textContent =
                "Đã lưu: " + savedWords.length;
            savedWordsList.textContent = "";

            savedWords.forEach(item => {
                const listItem =
                    document.createElement("li");
                const wordLine =
                    document.createElement("strong");
                const enLine =
                    document.createElement("span");
                const vnLine =
                    document.createElement("span");

                wordLine.textContent =
                    item.word
                    + (item.pinyin ? " - " + item.pinyin : "");
                enLine.className =
                    "saved-word-meta";
                vnLine.className =
                    "saved-word-meta";
                enLine.textContent =
                    "EN: " + (item.en || "");
                vnLine.textContent =
                    "VN: " + (item.vn || "");

                listItem.appendChild(wordLine);
                listItem.appendChild(enLine);
                listItem.appendChild(vnLine);
                savedWordsList.appendChild(listItem);
            });
        }


        function savePendingLookupEntry(event) {
            event?.preventDefault();
            event?.stopPropagation();

            if (
                isLookupLoading
                || !pendingLookupEntry?.word
            ) {
                return;
            }

            const exists = savedWords.some(item => (
                item.word === pendingLookupEntry.word
            ));
            const hadNoSavedWords =
                savedWords.length === 0;

            if (!exists) {
                savedWords.push(
                    {
                        word: pendingLookupEntry.word,
                        pinyin: pendingLookupEntry.pinyin || "",
                        en: pendingLookupEntry.en || "",
                        vn: pendingLookupEntry.vn || "",
                    }
                );
            }

            if (hadNoSavedWords) {
                isSavedWordsPanelOpen = true;
            }

            if (saveWordsStatus) {
                saveWordsStatus.textContent = "";
            }

            renderSavedWordsPanel();
            hideSaveSelectionMenu();

            window.getSelection()?.removeAllRanges();
        }


        document.addEventListener(
            "mouseup",
            event => {
                if (isDictionaryUiTarget(event.target)) {
                    return;
                }

                const selection =
                    window.getSelection();
                const selectedText =
                    selection?.toString() || "";
                const lookupText =
                    getChineseLookupText(selectedText);

                if (!lookupText) {
                    return;
                }

                showLookupMenu(
                    lookupText,
                    event.clientX,
                    event.clientY
                );
            }
        );


        document.addEventListener(
            "contextmenu",
            event => {
                if (isDictionaryUiTarget(event.target)) {
                    return;
                }

                const lookupText =
                    getChineseLookupText(
                        window.getSelection()?.toString() || ""
                    )
                    || getLookupTextFromElement(event.target);

                if (!lookupText || !saveSelectionMenu) {
                    hideSaveSelectionMenu();
                    return;
                }

                event.preventDefault();
                showLookupMenu(
                    lookupText,
                    event.clientX,
                    event.clientY
                );
            }
        );


        document.addEventListener(
            "click",
            event => {
                if (isDictionaryUiTarget(event.target)) {
                    return;
                }

                const selectedLookupText =
                    getChineseLookupText(
                        window.getSelection()?.toString() || ""
                    );

                if (selectedLookupText) {
                    return;
                }
                hideSaveSelectionMenu();
            }
        );


        if (saveSelectionButton) {
            saveSelectionButton.addEventListener(
                "click",
                savePendingLookupEntry
            );
        }


        if (closeSavedWordsButton) {
            closeSavedWordsButton.addEventListener(
                "click",
                () => {
                    isSavedWordsPanelOpen = false;
                    renderSavedWordsPanel();
                }
            );
        }


        if (savedWordsChip) {
            savedWordsChip.addEventListener(
                "click",
                () => {
                    isSavedWordsPanelOpen = true;
                    renderSavedWordsPanel();
                }
            );
        }


        if (downloadSavedWordsButton) {
            downloadSavedWordsButton.addEventListener(
                "click",
                async () => {
                    if (!savedWords.length || !outputFolder) {
                        return;
                    }

                    if (saveWordsStatus) {
                        saveWordsStatus.textContent =
                            "Đang ghi TXT...";
                    }

                    try {
                        const response = await fetch(
                            "/save_words",
                            {
                                method: "POST",
                                headers: {
                                    "Content-Type":
                                        "application/json",
                                },
                                body: JSON.stringify(
                                    {
                                        folder:
                                            outputFolder,
                                        words:
                                            savedWords,
                                    }
                                ),
                            }
                        );

                        const result =
                            await response.json();

                        if (!response.ok) {
                            throw new Error(
                                result.error || "Save failed"
                            );
                        }

                        if (saveWordsStatus) {
                            saveWordsStatus.textContent =
                                "Đã lưu: " + result.path;
                        }

                    } catch (error) {
                        if (saveWordsStatus) {
                            saveWordsStatus.textContent =
                                "Không lưu được TXT.";
                        }
                    }
                }
            );
        }


        function getWrittenEntries() {
            return characterInputs.flatMap(input => {
                const value = input.value.trim();

                if (value === "") {
                    return [];
                }

                return Array.from(value).map(character => (
                    {
                        character,
                        input,
                    }
                ));
            });
        }


        function buildDiff(expected, actual) {
            const matchCost = 0;
            const wrongCost = 3;
            const missingCost = 2;
            const extraCost = 2;
            const rowCount = expected.length + 1;
            const columnCount = actual.length + 1;
            const costs = Array.from(
                { length: rowCount },
                () => Array(columnCount).fill(0)
            );

            for (let row = 1; row < rowCount; row += 1) {
                costs[row][0] = row * missingCost;
            }

            for (let column = 1; column < columnCount; column += 1) {
                costs[0][column] = column * extraCost;
            }

            for (let row = 1; row < rowCount; row += 1) {
                for (let column = 1; column < columnCount; column += 1) {
                    const isMatch =
                        expected[row - 1] === actual[column - 1];
                    const diagonalCost =
                        costs[row - 1][column - 1]
                        + (isMatch ? matchCost : wrongCost);
                    const missing =
                        costs[row - 1][column] + missingCost;
                    const extra =
                        costs[row][column - 1] + extraCost;

                    costs[row][column] = Math.min(
                        diagonalCost,
                        missing,
                        extra
                    );
                }
            }

            const operations = [];
            let expectedIndex = expected.length;
            let actualIndex = actual.length;

            while (
                expectedIndex > 0
                || actualIndex > 0
            ) {
                if (
                    expectedIndex > 0
                    && actualIndex > 0
                ) {
                    const isMatch =
                        expected[expectedIndex - 1]
                        === actual[actualIndex - 1];
                    const diagonalCost =
                        costs[expectedIndex - 1][actualIndex - 1]
                        + (isMatch ? matchCost : wrongCost);

                    if (
                        costs[expectedIndex][actualIndex]
                        === diagonalCost
                    ) {
                        operations.push(
                            {
                                type: isMatch
                                    ? "match"
                                    : "wrong",
                                expected:
                                    expected[expectedIndex - 1],
                                actual:
                                    actual[actualIndex - 1],
                            }
                        );

                        expectedIndex -= 1;
                        actualIndex -= 1;
                        continue;
                    }
                }

                if (
                    expectedIndex > 0
                    && costs[expectedIndex][actualIndex]
                        === costs[expectedIndex - 1][actualIndex]
                            + missingCost
                ) {
                    operations.push(
                        {
                            type: "missing",
                            expected: expected[expectedIndex - 1],
                        }
                    );

                    expectedIndex -= 1;
                    continue;
                }

                if (actualIndex > 0) {
                    operations.push(
                        {
                            type: "extra",
                            actual: actual[actualIndex - 1],
                        }
                    );

                    actualIndex -= 1;
                }
            }

            return operations.reverse();
        }


        function appendDiffCharacter(
            character,
            className,
            title,
            container = checkDiff
        ) {
            if (!container) {
                return;
            }

            const element = document.createElement("span");

            element.className =
                "diff-char " + className;
            element.textContent = character;
            element.title = title;

            container.appendChild(element);
        }


        function appendDiffOperation(
            operation,
            container
        ) {
            if (operation.type === "match") {
                appendDiffCharacter(
                    operation.expected,
                    "diff-correct",
                    "Đúng",
                    container
                );
                return;
            }

            if (operation.type === "missing") {
                appendDiffCharacter(
                    operation.expected,
                    "diff-missing",
                    "Thiếu chữ này",
                    container
                );
                return;
            }

            if (operation.type === "wrong") {
                appendDiffCharacter(
                    operation.actual,
                    "diff-extra",
                    "Sai, đúng là " + operation.expected,
                    container
                );
                return;
            }

            appendDiffCharacter(
                operation.actual,
                "diff-extra",
                "Sai hoặc thừa",
                container
            );
        }


        function renderGroupedCheckDiff(operations) {
            if (!checkDiff) {
                return;
            }

            let operationIndex = 0;

            checkGroups.forEach(group => {
                const groupElement =
                    document.createElement("span");

                groupElement.className = "check-group";

                for (let index = 0; index < group.length; index += 1) {
                    while (
                        operationIndex < operations.length
                        && operations[operationIndex].type === "extra"
                    ) {
                        appendDiffOperation(
                            operations[operationIndex],
                            groupElement
                        );
                        operationIndex += 1;
                    }

                    if (operationIndex >= operations.length) {
                        break;
                    }

                    appendDiffOperation(
                        operations[operationIndex],
                        groupElement
                    );
                    operationIndex += 1;
                }

                checkDiff.appendChild(groupElement);
            });

            while (operationIndex < operations.length) {
                appendDiffOperation(
                    operations[operationIndex],
                    checkDiff
                );
                operationIndex += 1;
            }
        }


        function getSegmentExpectedCharacters(segment) {
            return segment.flatMap(group => {
                if (
                    typeof group === "object"
                    && group.check === false
                ) {
                    return [];
                }

                const text =
                    typeof group === "string"
                        ? group
                        : group.text;

                return Array.from(text || "");
            });
        }


        function appendCheckGroup(
            segment,
            groupCharacters
        ) {
            if (groupCharacters.length === 0) {
                return;
            }

            segment.push(
                {
                    text: groupCharacters.join(""),
                    check: true,
                }
            );
            groupCharacters.length = 0;
        }


        function appendCheckSegment(
            segments,
            segment,
            groupCharacters
        ) {
            appendCheckGroup(
                segment,
                groupCharacters
            );

            if (segment.length === 0) {
                return;
            }

            segments.push(
                {
                    groups: [...segment],
                    inputs: [...(segment.inputs || [])],
                }
            );
            segment.inputs = [];
            segment.length = 0;
        }


        function getDisplayedCheckSegments() {
            if (!characterGrid) {
                return [];
            }

            const segments = [];
            const segment = [];
            const groupCharacters = [];

            Array.from(characterGrid.children).forEach(element => {
                if (element.classList.contains("character-input")) {
                    const expectedCharacter =
                        element.dataset.expectedCharacter || "";

                    if (expectedCharacter) {
                        groupCharacters.push(expectedCharacter);
                    }

                    segment.inputs =
                        segment.inputs || [];
                    segment.inputs.push(element);
                    return;
                }

                if (element.classList.contains("text-space")) {
                    appendCheckGroup(
                        segment,
                        groupCharacters
                    );
                    return;
                }

                if (element.classList.contains("punctuation")) {
                    appendCheckGroup(
                        segment,
                        groupCharacters
                    );

                    segment.push(
                        {
                            text: element.textContent.trim(),
                            check: false,
                        }
                    );

                    if (
                        element.dataset.endsCheckSegment
                        === "true"
                    ) {
                        appendCheckSegment(
                            segments,
                            segment,
                            groupCharacters
                        );
                    }

                    return;
                }

                if (element.classList.contains("line-break")) {
                    appendCheckSegment(
                        segments,
                        segment,
                        groupCharacters
                    );
                }
            });

            appendCheckSegment(
                segments,
                segment,
                groupCharacters
            );

            return segments;
        }


        function getActualEntriesForSegment(
            segmentIndex
        ) {
            return characterInputs
                .filter(input => (
                    Number(input.dataset.checkSegment)
                    === segmentIndex
                ))
                .flatMap(input => {
                    const value = input.value.trim();

                    if (value === "") {
                        return [];
                    }

                    return Array.from(value).map(character => (
                        {
                            character,
                            input,
                        }
                    ));
                });
        }


        function renderSegmentCheckDiff(
            segment,
            operations
        ) {
            if (!checkDiff) {
                return;
            }

            let operationIndex = 0;

            segment.forEach(group => {
                const groupElement =
                    document.createElement("span");

                groupElement.className = "check-group";

                const groupText =
                    typeof group === "string"
                        ? group
                        : group.text;
                const shouldCheck =
                    typeof group === "string"
                    || group.check !== false;

                if (!shouldCheck) {
                    Array.from(groupText || "").forEach(character => {
                        appendDiffCharacter(
                            character,
                            "diff-punctuation",
                            "Dấu câu",
                            groupElement
                        );
                    });

                    checkDiff.appendChild(groupElement);
                    return;
                }

                for (let index = 0; index < groupText.length; index += 1) {
                    while (
                        operationIndex < operations.length
                        && operations[operationIndex].type === "extra"
                    ) {
                        appendDiffOperation(
                            operations[operationIndex],
                            groupElement
                        );
                        operationIndex += 1;
                    }

                    if (operationIndex >= operations.length) {
                        break;
                    }

                    appendDiffOperation(
                        operations[operationIndex],
                        groupElement
                    );
                    operationIndex += 1;
                }

                checkDiff.appendChild(groupElement);
            });

            while (operationIndex < operations.length) {
                appendDiffOperation(
                    operations[operationIndex],
                    checkDiff
                );
                operationIndex += 1;
            }
        }


        function normalizedToken(value) {
            return (value || "")
                .trim()
                .replace(/^[\p{P}\s]+|[\p{P}\s]+$/gu, "")
                .toLowerCase()
                .replace(/['’]/g, "");
        }


        function getAnswerUnits(groups) {
            const units = [];

            groups.forEach(group => {
                    const shouldCheck =
                        typeof group === "string"
                        || group.check !== false;

                    if (!shouldCheck) {
                        return;
                    }

                    const text =
                        typeof group === "string"
                            ? group
                            : group.text;

                    Array.from(text || "").forEach(character => {
                        const normalized =
                            normalizedToken(character);

                        if (!normalized) {
                            return;
                        }

                        units.push(
                            {
                                index: units.length,
                                text: character,
                                normalized,
                            }
                        );
                    });
            });

            return units;
        }


        function getInputUnits(inputs = characterInputs) {
            const units = [];

            inputs.forEach(input => {
                const value = input.value.trim();

                if (value === "") {
                    return;
                }

                Array.from(value).forEach(character => {
                    const normalized =
                        normalizedToken(character);

                    if (!normalized) {
                        return;
                    }

                    units.push(
                        {
                            text: character,
                            normalized,
                            input,
                        }
                    );
                });
            });

            return units;
        }


        function getInputUnitsFromText(
            text,
            input
        ) {
            return Array.from(text.trim()).flatMap(character => {
                const normalized =
                    normalizedToken(character);

                if (!normalized) {
                    return [];
                }

                return [
                    {
                        text: character,
                        normalized,
                        input,
                    },
                ];
            });
        }


        function alignSegmentAnswerUnits(
            answerUnits,
            inputs
        ) {
            const operations = [];
            let answerStartIndex = 0;
            let pendingInputs = [];

            function alignPending(
                answerEndIndex
            ) {
                if (
                    answerEndIndex <= answerStartIndex
                    && pendingInputs.length === 0
                ) {
                    return;
                }

                const answerSlice =
                    answerUnits.slice(
                        answerStartIndex,
                        answerEndIndex
                    );

                operations.push(
                    ...alignAnswerUnits(
                        answerSlice,
                        pendingInputs
                    )
                );
                pendingInputs = [];
            }

            inputs.forEach((input, inputIndex) => {
                const value = input.value.trim();

                if (value !== "") {
                    pendingInputs.push(
                        ...getInputUnitsFromText(
                            value,
                            input
                        )
                    );
                    return;
                }

                alignPending(inputIndex);

                if (answerUnits[inputIndex]) {
                    operations.push(
                        {
                            type: "missing",
                            unit: answerUnits[inputIndex],
                        }
                    );
                }

                answerStartIndex = inputIndex + 1;
            });

            alignPending(answerUnits.length);

            return operations;
        }


        function alignAnswerUnits(
            answerUnits,
            inputs
        ) {
            const answerCount = answerUnits.length;
            const inputCount = inputs.length;

            if (
                answerCount === 0
                && inputCount === 0
            ) {
                return [];
            }

            const matchCost = 0;
            const wrongCost = 3;
            const missingCost = 2;
            const extraCost = 2;
            const costs = Array.from(
                { length: answerCount + 1 },
                () => Array(inputCount + 1).fill(0)
            );

            for (let answerIndex = 1; answerIndex <= answerCount; answerIndex += 1) {
                costs[answerIndex][0] =
                    answerIndex * missingCost;
            }

            for (let inputIndex = 1; inputIndex <= inputCount; inputIndex += 1) {
                costs[0][inputIndex] =
                    inputIndex * extraCost;
            }

            for (let answerIndex = 1; answerIndex <= answerCount; answerIndex += 1) {
                for (let inputIndex = 1; inputIndex <= inputCount; inputIndex += 1) {
                    const answer =
                        answerUnits[answerIndex - 1];
                    const input =
                        inputs[inputIndex - 1];
                    const isMatch =
                        answer.normalized === input.normalized;
                    const diagonalCost =
                        costs[answerIndex - 1][inputIndex - 1]
                        + (isMatch ? matchCost : wrongCost);
                    const deleteCost =
                        costs[answerIndex - 1][inputIndex]
                        + missingCost;
                    const insertCost =
                        costs[answerIndex][inputIndex - 1]
                        + extraCost;

                    costs[answerIndex][inputIndex] =
                        Math.min(
                            diagonalCost,
                            deleteCost,
                            insertCost
                        );
                }
            }

            const operations = [];
            let answerIndex = answerCount;
            let inputIndex = inputCount;

            while (
                answerIndex > 0
                || inputIndex > 0
            ) {
                if (
                    answerIndex > 0
                    && inputIndex > 0
                ) {
                    const answer =
                        answerUnits[answerIndex - 1];
                    const input =
                        inputs[inputIndex - 1];
                    const isMatch =
                        answer.normalized === input.normalized;
                    const diagonalCost =
                        costs[answerIndex - 1][inputIndex - 1]
                        + (isMatch ? matchCost : wrongCost);

                    if (
                        costs[answerIndex][inputIndex]
                        === diagonalCost
                    ) {
                        operations.push(
                            {
                                type: isMatch
                                    ? "correct"
                                    : "wrong",
                                unit: answer,
                                input,
                            }
                        );
                        answerIndex -= 1;
                        inputIndex -= 1;
                        continue;
                    }
                }

                if (
                    answerIndex > 0
                    && costs[answerIndex][inputIndex]
                        === costs[answerIndex - 1][inputIndex]
                            + missingCost
                ) {
                    operations.push(
                        {
                            type: "missing",
                            unit: answerUnits[answerIndex - 1],
                        }
                    );
                    answerIndex -= 1;
                    continue;
                }

                if (inputIndex > 0) {
                    operations.push(
                        {
                            type: "extra",
                            input: inputs[inputIndex - 1],
                        }
                    );
                    inputIndex -= 1;
                }
            }

            return operations.reverse();
        }


        function makeAlignedReview(
            operations,
            answerCount
        ) {
            let correctCount = 0;
            let extraCount = 0;
            const statusByUnitIndex = {};
            const extrasBeforeUnit = {};
            let trailingExtras = [];
            const issues = [];
            const pendingExtras = [];

            function flushExtras(unit) {
                if (pendingExtras.length === 0) {
                    return;
                }

                extrasBeforeUnit[unit.index] = [
                    ...(extrasBeforeUnit[unit.index] || []),
                    ...pendingExtras,
                ];
                pendingExtras.length = 0;
            }

            operations.forEach(operation => {
                if (operation.type === "correct") {
                    flushExtras(operation.unit);
                    statusByUnitIndex[operation.unit.index] = {
                        type: "correct",
                    };
                    correctCount += 1;
                    return;
                }

                if (operation.type === "wrong") {
                    flushExtras(operation.unit);
                    statusByUnitIndex[operation.unit.index] = {
                        type: "wrong",
                        inputText: operation.input.text,
                    };
                    issues.push(
                        {
                            input: operation.input.text,
                            correctText: operation.unit.text,
                        }
                    );
                    return;
                }

                if (operation.type === "missing") {
                    flushExtras(operation.unit);
                    statusByUnitIndex[operation.unit.index] = {
                        type: "missing",
                    };
                    issues.push(
                        {
                            input: "",
                            correctText: operation.unit.text,
                        }
                    );
                    return;
                }

                const issue = {
                    input: operation.input.text,
                    correctText: "Remove this word",
                };
                pendingExtras.push(issue);
                issues.push(issue);
                extraCount += 1;
            });

            trailingExtras = [...pendingExtras];

            return {
                correctCount,
                totalCount: answerCount + extraCount,
                statusByUnitIndex,
                extrasBeforeUnit,
                trailingExtras,
                issues,
            };
        }


        function appendAlignedIssue(
            issue,
            container
        ) {
            appendDiffCharacter(
                issue.input,
                "diff-extra",
                issue.correctText === "Remove this word"
                    ? "Sai hoặc thừa"
                    : "Sai, đúng là " + issue.correctText,
                container
            );
        }


        function appendAlignedUnit(
            unit,
            review,
            container
        ) {
            const extras =
                review.extrasBeforeUnit[unit.index] || [];

            extras.forEach(issue => {
                appendAlignedIssue(
                    issue,
                    container
                );
            });

            const status =
                review.statusByUnitIndex[unit.index];

            if (!status) {
                appendDiffCharacter(
                    unit.text,
                    "diff-missing",
                    "Thiếu chữ này",
                    container
                );
                return;
            }

            if (status.type === "correct") {
                appendDiffCharacter(
                    unit.text,
                    "diff-correct",
                    "Đúng",
                    container
                );
                return;
            }

            if (status.type === "missing") {
                appendDiffCharacter(
                    unit.text,
                    "diff-missing",
                    "Thiếu chữ này",
                    container
                );
                return;
            }

            appendDiffCharacter(
                status.inputText,
                "diff-extra",
                "Sai, đúng là " + unit.text,
                container
            );
        }


        function renderAlignedReview(
            groups,
            review
        ) {
            let unitIndex = 0;

            groups.forEach(group => {
                    const groupElement =
                        document.createElement("span");

                    groupElement.className = "check-group";

                    const groupText =
                        typeof group === "string"
                            ? group
                            : group.text;
                    const shouldCheck =
                        typeof group === "string"
                        || group.check !== false;

                    if (!shouldCheck) {
                        Array.from(groupText || "").forEach(character => {
                            appendDiffCharacter(
                                character,
                                "diff-punctuation",
                                "Dấu câu",
                                groupElement
                            );
                        });

                        checkDiff.appendChild(groupElement);
                        return;
                    }

                    Array.from(groupText || "").forEach(character => {
                        appendAlignedUnit(
                            {
                                index: unitIndex,
                                text: character,
                            },
                            review,
                            groupElement
                        );
                        unitIndex += 1;
                    });

                    checkDiff.appendChild(groupElement);
            });

            review.trailingExtras.forEach(issue => {
                appendAlignedIssue(
                    issue,
                    checkDiff
                );
            });
        }


        function clearCheckState() {
            characterInputs.forEach(input => {
                input.disabled = false;
                input.classList.remove(
                    "correct",
                    "incorrect"
                );
            });

            if (checkResult) {
                checkResult.hidden = true;
            }

            if (replayWritingButton) {
                replayWritingButton.hidden = true;
            }

            if (checkWritingButton) {
                checkWritingButton.hidden = false;
            }

            if (checkDiff) {
                checkDiff.textContent = "";
            }
        }


        function showCheckResult() {
            if (
                !checkResult
                || !checkSummary
                || !checkDiff
                || !checkWritingButton
                || !replayWritingButton
            ) {
                return;
            }

            checkDiff.textContent = "";

            characterInputs.forEach(input => {
                input.classList.remove(
                    "correct",
                    "incorrect"
                );
                input.disabled = true;
            });

            const segments =
                getDisplayedCheckSegments();
            let correctCount = 0;
            let totalCount = 0;
            let missingCount = 0;
            let wrongCount = 0;

            segments.forEach(segment => {
                const groups =
                    segment.groups || [];
                const answerUnits =
                    getAnswerUnits(groups);
                const operations =
                    alignSegmentAnswerUnits(
                        answerUnits,
                        segment.inputs || []
                    );
                const review =
                    makeAlignedReview(
                        operations,
                        answerUnits.length
                    );
                const segmentMissingCount =
                    review.issues.filter(issue => (
                        issue.input === ""
                    )).length;
                const segmentWrongCount =
                    review.issues.length
                    - segmentMissingCount;

                correctCount += review.correctCount;
                totalCount += review.totalCount;
                missingCount += segmentMissingCount;
                wrongCount += segmentWrongCount;

                renderAlignedReview(
                    groups,
                    review
                );
            });

            checkSummary.textContent =
                "Đúng: "
                + correctCount
                + " / "
                + totalCount
                + " chữ. Thiếu: "
                + missingCount
                + ". Sai: "
                + wrongCount
                + ".";

            checkResult.hidden = false;
            checkWritingButton.hidden = true;
            replayWritingButton.hidden = false;
        }


        function replayWriting() {
            characterInputs.forEach(input => {
                input.value = "";
            });

            if (audio) {
                audio.pause();
                audio.currentTime = 0;
                updateAudioDisplay();
                updateCurrentReading();
            }

            if (progressBar) {
                progressBar.value = 0;
            }

            clearCheckState();

            if (characterInputs.length > 0) {
                focusInput(0);
            }
        }


        function focusInput(index) {
            const targetInput = characterInputs[index];

            if (!targetInput) {
                return;
            }

            targetInput.focus();

            const length = targetInput.value.length;

            try {
                targetInput.setSelectionRange(
                    length,
                    length
                );
            } catch (error) {
                console.error(error);
            }
        }


        function distributeText(startIndex, value) {
            if (isDistributingText) {
                return;
            }

            const characters = splitCharacters(value);

            if (characters.length === 0) {
                return;
            }

            isDistributingText = true;

            let targetIndex = startIndex;

            for (const character of characters) {
                if (
                    targetIndex
                    >= characterInputs.length
                ) {
                    break;
                }

                characterInputs[targetIndex].value =
                    character;

                targetIndex += 1;
            }

            isDistributingText = false;

            if (
                targetIndex
                < characterInputs.length
            ) {
                focusInput(targetIndex);
            } else if (
                characterInputs.length > 0
            ) {
                focusInput(
                    characterInputs.length - 1
                );
            }
        }


        characterInputs.forEach(
            (input, index) => {
                let isComposing = false;


                input.addEventListener(
                    "compositionstart",
                    () => {
                        isComposing = true;
                    }
                );


                input.addEventListener(
                    "compositionend",
                    event => {
                        isComposing = false;

                        const value =
                            event.target.value;

                        if (!value) {
                            return;
                        }

                        event.target.value = "";

                        distributeText(
                            index,
                            value
                        );
                    }
                );


                input.addEventListener(
                    "input",
                    event => {
                        if (
                            isDistributingText
                            || isComposing
                            || event.isComposing
                        ) {
                            return;
                        }

                        if (
                            event.inputType
                            && event.inputType.startsWith("delete")
                        ) {
                            input.value = "";
                            return;
                        }

                        const value = input.value;

                        if (!value) {
                            return;
                        }

                        input.value = "";

                        distributeText(
                            index,
                            value
                        );
                    }
                );


                input.addEventListener(
                    "paste",
                    event => {
                        event.preventDefault();

                        const pastedText =
                            event.clipboardData
                                .getData("text");

                        distributeText(
                            index,
                            pastedText
                        );
                    }
                );


                input.addEventListener(
                    "keydown",
                    event => {
                        if (
                            isComposing
                            || event.isComposing
                            || event.keyCode === 229
                        ) {
                            return;
                        }

                        if (
                            event.key === "ArrowRight"
                        ) {
                            if (audio) {
                                return;
                            }

                            event.preventDefault();
                            focusInput(index + 1);
                            return;
                        }

                        if (
                            event.key === "ArrowLeft"
                        ) {
                            if (audio) {
                                return;
                            }

                            event.preventDefault();
                            focusInput(index - 1);
                            return;
                        }

                        if (
                            event.key === "Backspace"
                        ) {
                            if (input.value !== "") {
                                event.preventDefault();
                                input.value = "";
                                return;
                            }

                            const previousInput =
                                characterInputs[
                                    index - 1
                                ];

                            if (previousInput) {
                                event.preventDefault();

                                previousInput.value = "";

                                focusInput(index - 1);
                            }

                            return;
                        }

                        if (
                            event.key === "Delete"
                        ) {
                            event.preventDefault();
                            event.stopPropagation();
                            input.value = "";
                            return;
                        }
                    }
                );
            }
        );


        if (checkWritingButton) {
            checkWritingButton.addEventListener(
                "click",
                showCheckResult
            );
        }


        if (replayWritingButton) {
            replayWritingButton.addEventListener(
                "click",
                replayWriting
            );
        }


        if (characterInputs.length > 0) {
            characterInputs[0].focus();
        }
    </script>
</body>
</html>
"""


def build_character_items(text: str) -> list:
    """
    Tạo danh sách phần tử để hiển thị phần luyện viết.

    - Chữ Hán: tạo ô input.
    - Dấu câu: hiển thị trực tiếp.
    - Xuống dòng: xuống dòng trên giao diện.
    - Khoảng trắng: tạo khoảng cách.
    """

    items = []

    chinese_pattern = re.compile(
        r"[\u3400-\u4dbf\u4e00-\u9fff]"
    )

    punctuation_characters = (
        "，。！？；：、"
        ",.!?;:"
        "“”‘’"
        "（）()"
        "《》〈〉"
        "【】[]"
        "…—-"
    )

    check_segment = 0

    for character in text:
        if chinese_pattern.fullmatch(character):
            items.append(
                {
                    "type": "input",
                    "character": character,
                    "check_segment": check_segment,
                }
            )

        elif character in punctuation_characters:
            items.append(
                {
                    "type": "punctuation",
                    "character": character,
                    "ends_check_segment":
                        has_sentence_punctuation(character),
                }
            )

            if has_sentence_punctuation(character):
                check_segment += 1

        elif character == "\n":
            items.append(
                {
                    "type": "line_break",
                    "character": "",
                }
            )
            check_segment += 1

        elif character.isspace():
            items.append(
                {
                    "type": "space",
                    "character": " ",
                }
            )

    return items


def extract_chinese_groups(text: str) -> list:
    groups = []

    for group in re.findall(r"\S+", text):
        chinese_group = extract_chinese_text(group)

        if chinese_group:
            groups.append(chinese_group)

    return groups


def extract_chinese_check_segments(text: str) -> list:
    segments = []
    current_segment = []
    current_group = []

    def flush_group() -> None:
        nonlocal current_group

        if not current_group:
            return

        current_segment.append(
            {
                "text": "".join(current_group),
                "check": True,
            }
        )
        current_group = []

    def flush_segment() -> None:
        nonlocal current_segment

        flush_group()

        if not current_segment:
            return

        segments.append(current_segment)
        current_segment = []

    for line in text.splitlines():
        for character in line:
            if re.fullmatch(
                r"[\u3400-\u4dbf\u4e00-\u9fff]",
                character,
            ):
                current_group.append(character)
                continue

            flush_group()

            if character.isspace():
                continue

            current_segment.append(
                {
                    "text": character,
                    "check": False,
                }
            )

            if has_sentence_punctuation(character):
                flush_segment()

        flush_segment()

    return segments


def extract_chinese_characters(text: str) -> list:
    chinese_pattern = re.compile(
        r"[\u3400-\u4dbf\u4e00-\u9fff]"
    )

    return [
        character
        for character in text
        if chinese_pattern.fullmatch(character)
    ]


def remove_markdown_marks(text: str) -> str:
    cleaned_lines = []

    for line in text.splitlines():
        line = re.sub(r"^\s*#+\s*", "", line)
        line = line.replace("**", "")
        cleaned_lines.append(line.rstrip())

    return "\n".join(cleaned_lines).strip()


def remove_chinese_group_spaces(text: str) -> str:
    lines = []

    for line in text.splitlines():
        line = re.sub(r"[ \t]+", "", line)
        lines.append(line)

    return "\n".join(lines).strip()


def count_chinese_characters(text: str) -> int:
    return len(
        re.findall(
            r"[\u3400-\u4dbf\u4e00-\u9fff]",
            text,
        )
    )


def extract_chinese_text(text: str) -> str:
    return "".join(
        re.findall(
            r"[\u3400-\u4dbf\u4e00-\u9fff]",
            text,
        )
    )


def split_grouped_text(text: str) -> list:
    groups = [
        group.strip()
        for group in re.split(r"[ \t]+", text.strip())
        if group.strip()
    ]

    if groups:
        return groups

    return [text.strip()] if text.strip() else []


def build_pinyin_tokens(pinyin_line: str) -> list:
    return [
        {
            "pinyin": group,
            "weight": 1,
        }
        for group in split_grouped_text(pinyin_line)
    ]


def normalize_pinyin_spacing(text: str) -> str:
    text = re.sub(r"\s+([,.;:!?，。！？；：])", r"\1", text)

    return text.strip()


def chinese_group_to_pinyin(chinese_group: str) -> str:
    syllables = lazy_pinyin(
        chinese_group,
        style=Style.TONE,
    )

    return normalize_pinyin_spacing(
        " ".join(syllables)
    )


def build_pinyin_tokens_from_chinese(
    chinese_line: str,
) -> list:
    return [
        {
            "pinyin": chinese_group_to_pinyin(
                chinese_group
            ),
            "weight": 1,
        }
        for chinese_group in split_grouped_text(chinese_line)
    ]


def build_reading_tokens(
    chinese_line: str,
) -> list:
    chinese_groups = split_grouped_text(chinese_line)

    if not chinese_groups:
        return []

    return [
        {
            "chinese": chinese_group,
            "weight": max(
                count_chinese_characters(chinese_group),
                1,
            ),
        }
        for chinese_group in chinese_groups
    ]


def has_sentence_punctuation(text: str) -> bool:
    return bool(
        re.search(
            r"[，。！？；：,!?;:]",
            text,
        )
    )


def clean_pinyin_source(text: str) -> str:
    cleaned_lines = []

    for line in text.splitlines():
        line = re.sub(r"^\s*#+\s*", "", line)
        line = line.replace("**", "").strip()

        if not line:
            cleaned_lines.append("")
            continue

        if re.search(
            r"[\u3400-\u4dbf\u4e00-\u9fff]",
            line,
        ):
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def strip_format_prefix(line: str, prefix: str) -> str:
    return line.split(prefix, 1)[1].strip()


def clean_chinese_format_line(line: str) -> str:
    content = strip_format_prefix(line, "中文:")

    return (
        content
        .replace("|", "")
        .replace(" ", "")
        .strip()
    )


def clean_pinyin_format_line(line: str) -> str:
    content = strip_format_prefix(line, "Pinyin:")
    content = content.replace("|", " ")
    content = re.sub(r"\s+", " ", content).strip()
    content = re.sub(r"\s+([,.;:!?，。！？；：])", r"\1", content)

    return content


def split_format_groups(line: str, prefix: str) -> list:
    content = strip_format_prefix(line, prefix)

    return [
        group.strip().replace(" ", "")
        if prefix == "中文:"
        else re.sub(r"\s+", " ", group.strip())
        for group in content.split("|")
        if group.strip()
    ]


def parse_aligned_lesson(text: str) -> dict:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not any(
        line.startswith("中文:")
        for line in lines
    ):
        return None

    clean_chinese_lines = []
    clean_pinyin_lines = []
    reading_segments = []

    index = 0

    while index < len(lines):
        chinese_line = lines[index]

        if not chinese_line.startswith("中文:"):
            index += 1
            continue

        if index + 1 >= len(lines):
            break

        pinyin_line = lines[index + 1]

        if not pinyin_line.startswith("Pinyin:"):
            index += 1
            continue

        clean_chinese = clean_chinese_format_line(
            chinese_line
        )

        clean_pinyin = clean_pinyin_format_line(
            pinyin_line
        )

        clean_chinese_lines.append(clean_chinese)
        clean_pinyin_lines.append(clean_pinyin)

        chinese_groups = split_format_groups(
            chinese_line,
            "中文:",
        )

        pinyin_groups = split_format_groups(
            pinyin_line,
            "Pinyin:",
        )

        tokens = [
            {
                "chinese": chinese_group,
                "weight": max(
                    count_chinese_characters(chinese_group),
                    1,
                ),
            }
            for chinese_group in chinese_groups
        ]

        if not tokens:
            tokens = build_reading_tokens(clean_chinese)

        pinyin_tokens = [
            {
                "pinyin": pinyin_group,
                "weight": 1,
            }
            for pinyin_group in pinyin_groups
        ]

        if not pinyin_tokens:
            pinyin_tokens = build_pinyin_tokens(clean_pinyin)

        reading_segments.append(
            {
                "chinese": clean_chinese,
                "pinyin": clean_pinyin,
                "weight": max(len(clean_chinese), 1),
                "tokens": tokens,
                "pinyin_tokens": pinyin_tokens,
            }
        )

        index += 2

    if not clean_chinese_lines:
        return None

    return {
        "text": "\n".join(clean_chinese_lines),
        "pinyin": "\n".join(clean_pinyin_lines),
        "reading_segments": reading_segments,
    }


def build_reading_segments(
    text: str,
) -> list:
    chinese_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not chinese_lines and text.strip():
        chinese_lines = [text.strip()]

    segments = []

    for chinese_line in chinese_lines:
        tokens = build_reading_tokens(chinese_line)
        pinyin_tokens = build_pinyin_tokens_from_chinese(
            chinese_line
        )
        pinyin_line = " ".join(
            token["pinyin"]
            for token in pinyin_tokens
        )

        segments.append(
            {
                "chinese": chinese_line,
                "pinyin": pinyin_line,
                "weight": max(
                    len(
                        remove_chinese_group_spaces(
                            chinese_line
                        )
                    ),
                    1,
                ),
                "tokens": tokens,
                "pinyin_tokens": pinyin_tokens,
            }
        )

    return segments


def flatten_reading_tokens(reading_segments: list) -> list:
    tokens = []

    for segment in reading_segments:
        tokens.extend(segment.get("tokens", []))

    return tokens


def split_tokens_into_sentence_groups(
    tokens: list,
    text_key: str,
) -> list:
    groups = []
    current_group = []

    for token in tokens:
        current_group.append(token)

        if has_sentence_punctuation(
            token.get(text_key, "")
        ):
            groups.append(current_group)
            current_group = []

    if current_group:
        groups.append(current_group)

    return groups


def distribute_pinyin_groups_by_count(
    pinyin_tokens: list,
    group_count: int,
) -> list:
    if group_count <= 0:
        return []

    groups = []
    token_count = len(pinyin_tokens)
    start_index = 0

    for group_index in range(group_count):
        end_index = round(
            token_count
            * (group_index + 1)
            / group_count
        )

        groups.append(pinyin_tokens[start_index:end_index])
        start_index = end_index

    return groups


def apply_pinyin_timings_to_reading_segments(
    reading_segments: list,
) -> None:
    for segment in reading_segments:
        chinese_tokens = [
            token
            for token in segment.get("tokens", [])
            if (
                token.get("start") is not None
                and token.get("end") is not None
            )
        ]

        pinyin_tokens = segment.get("pinyin_tokens", [])

        if not chinese_tokens or not pinyin_tokens:
            continue

        chinese_groups = split_tokens_into_sentence_groups(
            chinese_tokens,
            "chinese",
        )

        pinyin_groups = split_tokens_into_sentence_groups(
            pinyin_tokens,
            "pinyin",
        )

        if len(pinyin_groups) != len(chinese_groups):
            pinyin_groups = distribute_pinyin_groups_by_count(
                pinyin_tokens,
                len(chinese_groups),
            )

        for group_index, chinese_group in enumerate(
            chinese_groups
        ):
            if group_index >= len(pinyin_groups):
                break

            pinyin_group = pinyin_groups[group_index]

            if not pinyin_group:
                continue

            start_time = chinese_group[0]["start"]
            end_time = chinese_group[-1]["end"]
            duration = max(
                end_time - start_time,
                0.01,
            )
            step = duration / len(pinyin_group)

            for token_index, pinyin_token in enumerate(
                pinyin_group
            ):
                token_start = start_time + (step * token_index)

                pinyin_token["start"] = token_start
                pinyin_token["end"] = token_start + step


def apply_word_boundaries_to_reading_segments(
    reading_segments: list,
    boundaries: list,
) -> None:
    tokens = flatten_reading_tokens(reading_segments)
    character_timings = []

    for boundary in boundaries:
        boundary_text = extract_chinese_text(
            boundary.get("text", "")
        )

        if not boundary_text:
            continue

        character_duration = (
            boundary["end"] - boundary["start"]
        ) / len(boundary_text)

        for index, character in enumerate(boundary_text):
            start = (
                boundary["start"]
                + (character_duration * index)
            )

            character_timings.append(
                {
                    "text": character,
                    "start": start,
                    "end": start + character_duration,
                }
            )

    character_index = 0

    for token in tokens:
        target_text = extract_chinese_text(
            token.get("chinese", "")
        )

        if not target_text:
            continue

        token_timings = character_timings[
            character_index:character_index + len(target_text)
        ]

        if len(token_timings) != len(target_text):
            continue

        token["start"] = token_timings[0]["start"]
        token["end"] = token_timings[-1]["end"]
        character_index += len(target_text)


async def create_mp3(
    text: str,
    voice: str,
    output_path: Path,
) -> list:
    tts = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="-10%",
        boundary="WordBoundary",
    )

    boundaries = []

    with output_path.open("wb") as audio_file:
        async for chunk in tts.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])

            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                duration = chunk["duration"] / 10_000_000

                boundaries.append(
                    {
                        "text": chunk.get("text", ""),
                        "start": start,
                        "end": start + duration,
                    }
                )

    return boundaries


async def create_mp3_and_track(
    text: str,
    voice: str,
    output_path: Path,
    reading_segments: list,
) -> None:
    boundaries = await create_mp3(
        text=text,
        voice=voice,
        output_path=output_path,
    )

    apply_word_boundaries_to_reading_segments(
        reading_segments,
        boundaries,
    )

    apply_pinyin_timings_to_reading_segments(
        reading_segments
    )


@app.route("/", methods=["GET", "POST"])
def index():
    text = ""
    audio_url = None
    output_folder = ""
    error = None
    character_items = []
    reading_segments = []
    target_characters = []
    check_groups = []
    check_segments = []

    selected_voice = "zh-CN-XiaoxiaoNeural"

    if request.method == "POST":
        text = request.form.get(
            "text",
            "",
        ).strip()

        selected_voice = request.form.get(
            "voice",
            "zh-CN-XiaoxiaoNeural",
        )

        if selected_voice not in VOICES.values():
            selected_voice = (
                "zh-CN-XiaoxiaoNeural"
            )

        if not text:
            error = "Bạn chưa nhập văn bản."

        else:
            aligned_lesson = parse_aligned_lesson(
                text
            )

            processed_text = text
            display_text = remove_markdown_marks(text)

            if aligned_lesson:
                processed_text = aligned_lesson["text"]
                display_text = processed_text

            else:
                processed_text = remove_chinese_group_spaces(
                    display_text
                )

            lesson_folder = unique_output_folder(
                safe_output_folder_name(display_text)
            )
            filename = "audio.mp3"
            output_path = lesson_folder / filename

            character_items = build_character_items(
                processed_text
            )

            target_characters = extract_chinese_characters(
                processed_text
            )

            check_groups = extract_chinese_groups(
                display_text
            )

            check_segments = extract_chinese_check_segments(
                display_text
            )

            if aligned_lesson:
                reading_segments = aligned_lesson[
                    "reading_segments"
                ]

            else:
                reading_segments = build_reading_segments(
                    display_text,
                )

            try:
                asyncio.run(
                    create_mp3_and_track(
                        text=processed_text,
                        voice=selected_voice,
                        output_path=output_path,
                        reading_segments=reading_segments,
                    )
                )

                audio_url = (
                    f"/outputs/{lesson_folder.name}/{filename}"
                )
                output_folder = lesson_folder.name

            except Exception as exc:
                print(f"TTS error: {exc}")

                error = (
                    "Không thể tạo MP3. "
                    "Hãy kiểm tra kết nối Internet "
                    "rồi thử lại."
                )

    return render_template_string(
        HTML_PAGE,
        text=text,
        voices=VOICES,
        selected_voice=selected_voice,
        audio_url=audio_url,
        output_folder=output_folder,
        error=error,
        character_items=character_items,
        reading_segments=reading_segments,
        target_characters=target_characters,
        check_groups=check_groups,
        check_segments=check_segments,
    )


@app.route("/lookup")
def lookup_word():
    return jsonify(
        lookup_dictionary_word(
            request.args.get(
                "word",
                "",
            )
        )
    )


@app.route("/save_words", methods=["POST"])
def save_words():
    payload = request.get_json(silent=True) or {}
    folder = get_safe_output_subfolder(
        str(payload.get("folder", ""))
    )

    if folder is None:
        return jsonify(
            {
                "error": "Folder không hợp lệ.",
            }
        ), 400

    words = payload.get("words", [])

    if not isinstance(words, list):
        return jsonify(
            {
                "error": "Danh sách từ không hợp lệ.",
            }
        ), 400

    output_path = folder / SAVED_WORDS_FILENAME
    output_path.write_text(
        format_saved_words_text(words),
        encoding="utf-8",
    )

    return jsonify(
        {
            "path": str(output_path),
        }
    )


@app.route("/outputs/<path:filename>")
def output_file(filename: str):
    return send_from_directory(
        OUTPUT_DIR,
        filename,
        as_attachment=False,
    )


@app.route("/ping", methods=["POST"])
def ping():
    return Response(status=204)


if __name__ == "__main__":
    debug_mode = os.environ.get(
        "CHINESE_TTS_DEBUG",
        "0",
    ) == "1"

    if (
        not debug_mode
        or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    ):
        threading.Thread(
            target=idle_shutdown_watchdog,
            daemon=True,
        ).start()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=debug_mode,
    )
