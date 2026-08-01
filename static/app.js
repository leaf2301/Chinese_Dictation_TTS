/* ── Chinese Dictation App ────────────────────────────────── */

// DOM refs
const textInput = document.getElementById("textInput");
const voiceSelect = document.getElementById("voiceSelect");
const btnGenerate = document.getElementById("btnGenerate");
const statusEl = document.getElementById("status");

const trackingSection = document.getElementById("trackingSection");
const audioBar = document.getElementById("audioBar");
const btnPlay = document.getElementById("btnPlay");
const progressBar = document.getElementById("progressBar");
const progressFill = document.getElementById("progressFill");
const timeDisplay = document.getElementById("timeDisplay");
const trackingWords = document.getElementById("trackingWords");
const audioEl = document.getElementById("audioEl");
const speedToggle = document.getElementById("speedToggle");
const speedMenu = document.getElementById("speedMenu");

const dictationSection = document.getElementById("dictationSection");
const dictationGrid = document.getElementById("dictationGrid");
const btnCheck = document.getElementById("btnCheck");
const btnReplay = document.getElementById("btnReplay");
const scoreBar = document.getElementById("scoreBar");
const scoreFill = document.getElementById("scoreFill");
const scorePercent = document.getElementById("scorePercent");
const scoreDetail = document.getElementById("scoreDetail");

const pctSelect = document.getElementById("pctSelect");
const btnApplyPct = document.getElementById("btnApplyPct");

// State
let wordBoundaries = [];
let originalWords = [];
let isChecked = false;
let trackingHidden = true;
let currentRawText = "";
let currentFolderName = "";
let globalPinyinMap = {};

/* ── Load Voices ─────────────────────────────────────────── */
async function loadVoices() {
  try {
    const res = await fetch("/api/voices");
    const voices = await res.json();
    voiceSelect.innerHTML = "";
    voices.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v.short;
      opt.textContent = `${v.name || v.short}  (${v.gender})`;
      voiceSelect.appendChild(opt);
    });
    const defaultVoice = voices.find((v) => v.short === "zh-CN-XiaoxiaoNeural") || voices[0];
    if (defaultVoice) voiceSelect.value = defaultVoice.short;
    btnGenerate.disabled = false;
  } catch (e) {
    voiceSelect.innerHTML = '<option value="">Failed to load voices</option>';
    setStatus("Could not load voices. Is the server running?", true);
  }
}

/* ── Generate TTS ────────────────────────────────────────── */
btnGenerate.addEventListener("click", async () => {
  const text = textInput.value.trim();
  if (!text) {
    setStatus("Please paste some Chinese text first.", true);
    return;
  }

  btnGenerate.classList.add("loading");
  btnGenerate.disabled = true;
  setStatus("Generating audio…");

  try {
    const res = await fetch("/api/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice: voiceSelect.value }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Server error");
    }

    const data = await res.json();
    wordBoundaries = data.word_boundaries || [];
    currentFolderName = data.folder_name || "";
    globalPinyinMap = data.pinyin_map || {};
    audioEl.src = data.audio_url;
    audioEl.load();

    buildTrackingWords();
    buildDictation(text);

    trackingSection.classList.add("visible");
    audioBar.classList.add("visible");
    dictationSection.classList.add("visible");
    if (btnApplyPct) btnApplyPct.disabled = false;
    if (pctSelect) pctSelect.disabled = false;
    setStatus("Ready! Press play to listen, then type your dictation below.");
  } catch (e) {
    setStatus("Error: " + e.message, true);
  } finally {
    btnGenerate.classList.remove("loading");
    btnGenerate.disabled = false;
  }
});

/* ── Tracking Words ──────────────────────────────────────── */
let lastActiveIndex = -1;

function renderPinyinBelow(text, pinyinStr) {
  if (!/[\u3400-\u4dbf\u4e00-\u9fff]/.test(text)) {
    return `<span class="ruby-pair"><span class="hanzi">${text}</span></span>`;
  }
  const chars = Array.from(text);
  const pinyins = pinyinStr ? pinyinStr.trim().split(/\s+/) : [];

  if (chars.length > 0 && chars.length === pinyins.length) {
    return chars
      .map(
        (ch, i) =>
          `<span class="ruby-pair"><span class="hanzi">${ch}</span><span class="pinyin">${pinyins[i]}</span></span>`
      )
      .join("");
  } else {
    return `<span class="ruby-pair"><span class="hanzi">${text}</span>${pinyinStr ? `<span class="pinyin">${pinyinStr}</span>` : ''}</span>`;
  }
}

function buildTrackingWords() {
  lastActiveIndex = -1;
  trackingWords.innerHTML = "";

  if (wordBoundaries && wordBoundaries.length > 0) {
    wordBoundaries.forEach((wb, idx) => {
      const span = document.createElement("span");
      span.className = "track-word";
      span.dataset.idx = idx;

      const pinyinStr = wb.pinyin || globalPinyinMap[wb.text] || "";
      span.innerHTML = renderPinyinBelow(wb.text, pinyinStr);

      span.style.display = "none";
      trackingWords.appendChild(span);
    });
  } else {
    trackingWords.innerHTML = '<span class="track-word active"><span class="ruby-pair"><span class="hanzi">…</span></span></span>';
  }

  trackingWords.scrollTop = 0;
  trackingWords.classList.toggle("hidden", trackingHidden);
  const btnHideTrack = document.getElementById("btnHideTrack");
  if (btnHideTrack) btnHideTrack.textContent = trackingHidden ? "👁 Show" : "👁 Hide";
}

function updateTracking() {
  if (!wordBoundaries || wordBoundaries.length === 0) return;

  const time = audioEl.currentTime;
  let activeIdx = -1;

  for (let i = 0; i < wordBoundaries.length; i++) {
    const wb = wordBoundaries[i];
    if (time >= wb.start) {
      activeIdx = i;
    } else {
      break;
    }
  }

  if (activeIdx !== lastActiveIndex) {
    lastActiveIndex = activeIdx;
    const wordSpans = trackingWords.querySelectorAll(".track-word");

    wordSpans.forEach((span, idx) => {
      if (idx < activeIdx) {
        span.className = "track-word past";
        span.style.display = "inline-block";
      } else if (idx === activeIdx) {
        span.className = "track-word active";
        span.style.display = "inline-block";

        let spanTop = span.offsetTop;
        let parent = span.offsetParent;
        while (parent && parent !== trackingWords) {
          spanTop += parent.offsetTop;
          parent = parent.offsetParent;
        }

        const spanBottom = spanTop + span.offsetHeight;
        const visibleTop = trackingWords.scrollTop;
        const visibleBottom = visibleTop + trackingWords.clientHeight;

        if (spanBottom > visibleBottom) {
          trackingWords.scrollTop = spanBottom - trackingWords.clientHeight;
        } else if (spanTop < visibleTop) {
          trackingWords.scrollTop = spanTop;
        }
      } else {
        span.className = "track-word";
        span.style.display = "none";
      }
    });
  }
}

/* ── Audio Player ────────────────────────────────────────── */
btnPlay.addEventListener("click", togglePlay);

audioEl.addEventListener("timeupdate", () => {
  updateTracking();
  updateProgress();
});

audioEl.addEventListener("ended", () => {
  btnPlay.textContent = "▶";
});

function updateProgress() {
  if (audioEl.duration) {
    const pct = (audioEl.currentTime / audioEl.duration) * 100;
    progressFill.style.width = pct + "%";
    timeDisplay.textContent = `${fmtTime(audioEl.currentTime)} / ${fmtTime(audioEl.duration)}`;
  }
}

progressBar.addEventListener("click", (e) => {
  if (audioEl.duration) {
    const rect = progressBar.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    audioEl.currentTime = pct * audioEl.duration;
  }
});

// Speed Dropdown logic
speedToggle.addEventListener("click", (e) => {
  e.stopPropagation();
  speedMenu.classList.toggle("open");
});

document.addEventListener("click", (e) => {
  if (!speedMenu.contains(e.target) && e.target !== speedToggle) {
    speedMenu.classList.remove("open");
  }
});

const speedSlider = document.getElementById("speedSlider");
const speedVal = document.getElementById("speedVal");

if (speedSlider) {
  speedSlider.addEventListener("input", (e) => {
    const speed = parseFloat(e.target.value);
    audioEl.playbackRate = speed;
    const formattedSpeed = speed.toFixed(1) + "×";
    speedToggle.textContent = formattedSpeed;
    if (speedVal) speedVal.textContent = formattedSpeed;
    saveSetting({ pace: speed });
  });
}

function fmtTime(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

/* ── Backward / Forward Skip ─────────────────────────────── */
let backwardSec = 3;
let forwardSec = 10;
const MIN_SKIP = 3;
const MAX_SKIP = 10;

const btnBackward = document.getElementById("btnBackward");
const btnForward = document.getElementById("btnForward");
const bwdVal = document.getElementById("bwdVal");
const fwdVal = document.getElementById("fwdVal");

function doBackward() {
  audioEl.currentTime = Math.max(0, audioEl.currentTime - backwardSec);
}

function doForward() {
  if (audioEl.duration) {
    audioEl.currentTime = Math.min(audioEl.duration, audioEl.currentTime + forwardSec);
  }
}

function togglePlay() {
  if (audioEl.paused) {
    audioEl.play();
    btnPlay.textContent = "⏸";
  } else {
    audioEl.pause();
    btnPlay.textContent = "▶";
  }
}

btnBackward.addEventListener("click", doBackward);
btnForward.addEventListener("click", doForward);

// − / + adjustment buttons
document.getElementById("bwdMinus").addEventListener("click", () => {
  backwardSec = Math.max(MIN_SKIP, backwardSec - 1);
  bwdVal.textContent = backwardSec;
  saveSetting({ backward_sec: backwardSec });
});
document.getElementById("bwdPlus").addEventListener("click", () => {
  backwardSec = Math.min(MAX_SKIP, backwardSec + 1);
  bwdVal.textContent = backwardSec;
  saveSetting({ backward_sec: backwardSec });
});
document.getElementById("fwdMinus").addEventListener("click", () => {
  forwardSec = Math.max(MIN_SKIP, forwardSec - 1);
  fwdVal.textContent = forwardSec;
  saveSetting({ forward_sec: forwardSec });
});
document.getElementById("fwdPlus").addEventListener("click", () => {
  forwardSec = Math.min(MAX_SKIP, forwardSec + 1);
  fwdVal.textContent = forwardSec;
  saveSetting({ forward_sec: forwardSec });
});

/* ── Keyboard Shortcuts ──────────────────────────────────── */
function toggleTracking() {
  trackingHidden = !trackingHidden;
  trackingWords.classList.toggle("hidden", trackingHidden);
  const btnHideTrack = document.getElementById("btnHideTrack");
  if (btnHideTrack) btnHideTrack.textContent = trackingHidden ? "👁 Show" : "👁 Hide";
}

document.addEventListener("keydown", (e) => {
  const isInput = e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.isContentEditable;

  // ~ or ` (Backquote key above Tab) → ALWAYS toggle tracking words visibility & prevent text input
  if (e.key === "`" || e.key === "~" || e.code === "Backquote" || e.keyCode === 192 || e.key === "·" || e.key === "｀" || e.key === "～") {
    e.preventDefault();
    toggleTracking();
    return;
  }

  // Space or Shift → ALWAYS play/pause for Chinese TTS (NEVER trigger IME candidate selection with Space!)
  if (e.key === " " || e.code === "Space" || e.keyCode === 32 || e.key === "Shift" || e.code === "ShiftLeft" || e.code === "ShiftRight") {
    e.preventDefault();
    e.stopPropagation();
    togglePlay();
    return;
  }
  // ArrowLeft → ALWAYS backward skip
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    doBackward();
    return;
  }
  // ArrowRight → ALWAYS forward skip
  if (e.key === "ArrowRight") {
    e.preventDefault();
    doForward();
    return;
  }
});

document.addEventListener("beforeinput", (e) => {
  if (e.data === " " || e.inputType === "insertText" && e.data === " ") {
    e.preventDefault();
  }
  if (e.data && (e.data.includes("`") || e.data.includes("~") || e.data.includes("·") || e.data.includes("｀") || e.data.includes("～"))) {
    e.preventDefault();
  }
});

/* ── Dictation ───────────────────────────────────────────── */

/**
 * Normalize a word for comparison: lowercase, strip punctuation.
 */
function normalizeWord(w) {
  if (!w) return "";
  return w.trim().toLowerCase().replace(/[^\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFFa-zA-Z0-9]/gi, "");
}

/**
 * Clean text of markdown / special characters for TTS and dictation.
 */
function cleanTextForTTS(text) {
  return text
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/\*{1,3}(.*?)\*{1,3}/g, "$1")
    .replace(/_{1,3}(.*?)_{1,3}/g, "$1")
    .replace(/~~(.*?)~~/g, "$1")
    .replace(/`{1,3}(.*?)`{1,3}/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/<[^>]+>/g, "")
    .replace(/^\s*[-*•]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/[#@^\\|<>{}[\]~]/g, "")
    .replace(/\n{2,}/g, "\n")
    .replace(/[ \t]+/g, " ")
    .trim();
}

/**
 * Tokenize a line into words or individual Chinese characters.
 */
function tokenizeLine(line) {
  const pattern = /[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF]|[a-zA-Z0-9'’]+|[^\s\w\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF]+/g;
  const matches = line.match(pattern) || [];
  return matches;
}

/**
 * Determine which word indices in a line should be hidden.
 */
function determineHiddenIndices(wordsInLine, hiddenPct) {
  const N = wordsInLine.length;
  const hiddenSet = new Set();

  if (N === 0) return hiddenSet;
  if (hiddenPct >= 100) {
    for (let i = 0; i < N; i++) hiddenSet.add(i);
    return hiddenSet;
  }

  let targetCount = Math.round(N * (hiddenPct / 100));
  if (N >= 2) {
    targetCount = Math.max(1, Math.min(N - 1, targetCount));
  } else {
    targetCount = 1;
  }

  const bucketSize = N / targetCount;
  for (let b = 0; b < targetCount; b++) {
    const start = Math.floor(b * bucketSize);
    const end = Math.floor((b + 1) * bucketSize);
    const chosen = start + Math.floor(Math.random() * Math.max(1, end - start));
    hiddenSet.add(chosen);
  }

  return hiddenSet;
}

function buildDictation(text) {
  currentRawText = text;
  dictationGrid.innerHTML = "";
  isChecked = false;
  originalWords = [];

  const hiddenPct = parseInt(pctSelect ? pctSelect.value : 100, 10) || 100;
  const rawLines = text.split("\n");
  let wordCounter = 0;

  rawLines.forEach((rawLine) => {
    const cleanedLine = cleanTextForTTS(rawLine);
    const wordsInLine = tokenizeLine(cleanedLine);
    if (wordsInLine.length === 0) return;

    if (dictationGrid.children.length > 0) {
      const lineBreak = document.createElement("div");
      lineBreak.className = "dictation-break";
      dictationGrid.appendChild(lineBreak);
    }

    const wordTokens = wordsInLine.filter((w) => !/^[^\s\w\u3400-\u4dbf\u4e00-\u9fff]+$/.test(w));
    const hiddenSet = determineHiddenIndices(wordTokens, hiddenPct);
    let wordIdxInLine = 0;

    wordsInLine.forEach((word) => {
      const isPunct = /^[^\s\w\u3400-\u4dbf\u4e00-\u9fff]+$/.test(word);
      if (isPunct) {
        const punctSpan = document.createElement("span");
        punctSpan.className = "dictation-punct";
        punctSpan.textContent = word;
        dictationGrid.appendChild(punctSpan);
      } else {
        const wIdx = wordIdxInLine++;
        const i = wordCounter++;
        originalWords.push(word);

        const isHidden = hiddenSet.has(wIdx);
        const box = document.createElement("div");
        box.className = "word-box" + (isHidden ? "" : " unhidden");

      if (isHidden) {
        const input = document.createElement("input");
        input.type = "text";
        input.dataset.index = i;
        input.dataset.answer = word;
        const charW = Math.max(word.length * 0.75 + 1.5, 3.5);
        input.style.width = charW + "em";
        input.autocomplete = "off";
        input.spellcheck = false;

        const badge = document.createElement("div");
        badge.className = "word-badge";

        box.appendChild(input);
        box.appendChild(badge);

        // Key handlers
        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            handleAdvance(input, i);
          }
          if (e.key === "Backspace" && input.value === "" && i > 0) {
            e.preventDefault();
            const inputs = Array.from(dictationGrid.querySelectorAll("input"));
            let prevInput = null;
            inputs.forEach((inp) => {
              if (parseInt(inp.dataset.index, 10) < i) prevInput = inp;
            });
            if (prevInput) {
              prevInput.focus();
              prevInput.setSelectionRange(prevInput.value.length, prevInput.value.length);
            }
          }
          if (e.key === "Tab") {
            e.preventDefault();
            const inputs = Array.from(dictationGrid.querySelectorAll("input"));
            const currentPos = inputs.indexOf(input);
            const nextPos = e.shiftKey ? currentPos - 1 : currentPos + 1;
            if (nextPos >= 0 && nextPos < inputs.length) inputs[nextPos].focus();
          }
        });

        // Clear state when user focuses missing input
        input.addEventListener("focus", () => {
          if (input.classList.contains("missing")) {
            input.placeholder = "";
            input.classList.remove("missing");
          }
        });

        let isComposing = false;

        input.addEventListener("compositionstart", () => {
          isComposing = true;
        });

        input.addEventListener("compositionend", () => {
          isComposing = false;
          handleMultiCharInput(input);
        });

        // Live feedback: clear check state when user modifies & auto-fill multi-char input
        input.addEventListener("input", () => {
          if (/[\`~·｀～]/.test(input.value)) {
            input.value = input.value.replace(/[`~·｀～]/g, "");
          }
          box.removeAttribute("data-tooltip");
          if (isChecked) {
            input.placeholder = "";
            input.classList.remove("correct", "incorrect", "missing");
            box.querySelector(".word-badge").textContent = "";
            box.querySelector(".word-badge").className = "word-badge";
          }
          if (!isComposing) {
            handleMultiCharInput(input);
          }
        });
      } else {
        // Unhidden hint word
        const unhiddenSpan = document.createElement("div");
        unhiddenSpan.className = "unhidden-word";
        unhiddenSpan.textContent = word;

        const dummyBadge = document.createElement("div");
        dummyBadge.className = "word-badge";

        box.appendChild(unhiddenSpan);
        box.appendChild(dummyBadge);
      }

      dictationGrid.appendChild(box);
      }
    });
  });

  // Focus first input
  const firstInput = dictationGrid.querySelector("input");
  if (firstInput) firstInput.focus();

  scoreBar.classList.remove("visible");
}

function handleAdvance(input, index) {
  const inputs = Array.from(dictationGrid.querySelectorAll("input"));
  const currentPos = inputs.indexOf(input);
  if (currentPos + 1 < inputs.length) {
    inputs[currentPos + 1].focus();
  }
}

function handleMultiCharInput(input) {
  const val = input.value;
  if (!val) return;

  const hanziRegex = /[\u3400-\u4dbf\u4e00-\u9fff]/;
  const chars = Array.from(val.trim());

  // Only auto-fill/auto-advance when input contains actual Chinese Hanzi characters (from IME candidate selection 1,2,3,4,5...)
  const isOnlyHanzi = chars.every((ch) => hanziRegex.test(ch));
  if (!isOnlyHanzi) return;

  const inputs = Array.from(dictationGrid.querySelectorAll("input"));
  const currentPos = inputs.indexOf(input);
  if (currentPos === -1) return;

  const targetAnswer = input.dataset.answer || "";

  if (chars.length > targetAnswer.length && chars.length > 1) {
    let charIdx = 0;
    let filledCount = 0;
    for (let p = currentPos; p < inputs.length && charIdx < chars.length; p++) {
      const targetInput = inputs[p];
      const ansLen = (targetInput.dataset.answer || "").length || 1;
      const sub = chars.slice(charIdx, charIdx + ansLen).join("");
      targetInput.value = sub;
      charIdx += ansLen;
      filledCount++;

      targetInput.classList.remove("correct", "incorrect", "missing");
      targetInput.placeholder = "";
      const parentBox = targetInput.parentElement;
      if (parentBox) {
        parentBox.removeAttribute("data-tooltip");
        const badge = parentBox.querySelector(".word-badge");
        if (badge) {
          badge.textContent = "";
          badge.className = "word-badge";
        }
      }
    }

    const nextPos = Math.min(currentPos + filledCount, inputs.length - 1);
    if (inputs[nextPos]) {
      inputs[nextPos].focus();
    }
  } else if (chars.length >= 1) {
    // 1-character Hanzi selection (e.g. user pressed 1 for '我') -> Auto-advance to next empty box
    const nextPos = currentPos + 1;
    if (inputs[nextPos]) {
      inputs[nextPos].focus();
    }
  }
}

/* ── Check Logic ─────────────────────────────────────────── */
btnCheck.addEventListener("click", () => {
  const inputs = dictationGrid.querySelectorAll("input");
  const boxes = dictationGrid.querySelectorAll(".word-box");

  if (isChecked) {
    inputs.forEach((input) => {
      input.placeholder = "";
      input.classList.remove("correct", "incorrect", "missing");
    });
    boxes.forEach((box) => {
      box.removeAttribute("data-tooltip");
      const badge = box.querySelector(".word-badge");
      if (badge) {
        badge.textContent = "";
        badge.className = "word-badge";
      }
    });
    isChecked = false;
    btnCheck.classList.remove("active");
    scoreBar.classList.remove("visible");
    return;
  }

  let correctCount = 0;
  let wrongCount = 0;
  let missingCount = 0;

  inputs.forEach((input) => {
    const answer = input.dataset.answer;
    const typed = input.value.trim();
    const badge = input.parentElement.querySelector(".word-badge");
    const box = input.parentElement;

    input.classList.remove("correct", "incorrect", "missing");
    input.placeholder = "";
    if (badge) badge.className = "word-badge";
    box.removeAttribute("data-tooltip");

    const normTyped = normalizeWord(typed);
    const normAnswer = normalizeWord(answer);
    const isMatch = (normTyped !== "" && normTyped === normAnswer) || (typed.trim() === answer.trim());

    if (!typed) {
      input.classList.add("missing");
      input.placeholder = answer;
      if (badge) badge.textContent = "";
      missingCount++;
    } else if (isMatch) {
      input.classList.add("correct");
      if (badge) {
        badge.textContent = "✓";
        badge.classList.add("badge-correct");
      }
      correctCount++;
    } else {
      input.classList.add("incorrect");
      if (badge) {
        badge.textContent = "✗";
        badge.classList.add("badge-wrong");
      }
      box.dataset.tooltip = answer;
      wrongCount++;
    }
  });

  isChecked = true;
  btnCheck.classList.add("active");

  const total = inputs.length;
  const pct = total > 0 ? Math.round((correctCount / total) * 100) : 0;
  scoreFill.style.width = pct + "%";
  scorePercent.textContent = pct + "%";

  scoreDetail.textContent = `${correctCount} correct · ${wrongCount} wrong · ${missingCount} missing  (${total} blanks)`;

  if (pct >= 80) {
    scoreFill.style.background = "var(--success)";
    scorePercent.style.color = "var(--success)";
  } else if (pct >= 50) {
    scoreFill.style.background = "var(--warning)";
    scorePercent.style.color = "var(--warning)";
  } else {
    scoreFill.style.background = "var(--error)";
    scorePercent.style.color = "var(--error)";
  }

  scoreBar.classList.add("visible");
});

btnReplay.addEventListener("click", () => {
  const inputs = dictationGrid.querySelectorAll("input");
  const boxes = dictationGrid.querySelectorAll(".word-box");
  inputs.forEach((input) => {
    input.value = "";
    input.placeholder = "";
    input.classList.remove("correct", "incorrect", "missing");
  });
  boxes.forEach((box) => {
    box.removeAttribute("data-tooltip");
    const badge = box.querySelector(".word-badge");
    if (badge) {
      badge.textContent = "";
      badge.className = "word-badge";
    }
  });
  isChecked = false;
  btnCheck.classList.remove("active");
  scoreBar.classList.remove("visible");
  if (btnApplyPct) btnApplyPct.disabled = false;
  if (pctSelect) pctSelect.disabled = false;

  audioEl.currentTime = 0;
  audioEl.pause();
  btnPlay.textContent = "▶";

  if (inputs.length) inputs[0].focus();
});

/* ── Helpers ─────────────────────────────────────────────── */
function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.className = "status" + (isError ? " error" : "");
}

/* ── Hide / Show Tracking ────────────────────────────────── */
const btnHideTrack = document.getElementById("btnHideTrack");
if (btnHideTrack) {
  btnHideTrack.addEventListener("click", toggleTracking);
}

/* ── Hidden Percentage Select & Apply ────────────────────── */
if (pctSelect) {
  pctSelect.addEventListener("change", () => {
    saveSetting({ hidden_pct: parseInt(pctSelect.value, 10) });
  });
}

if (btnApplyPct) {
  btnApplyPct.addEventListener("click", () => {
    if (pctSelect) saveSetting({ hidden_pct: parseInt(pctSelect.value, 10) });
    if (currentRawText) {
      buildDictation(currentRawText);
      btnApplyPct.disabled = true;
      if (pctSelect) pctSelect.disabled = true;
    }
  });
}

/* ── Context Popup & Vocabulary Feature ──────────────────── */
const contextPopup = document.getElementById("contextPopup");
const popupStt = document.getElementById("popupStt");
const popupWord = document.getElementById("popupWord");
const popupPhonetic = document.getElementById("popupPhonetic");
const popupEn = document.getElementById("popupEn");
const popupVn = document.getElementById("popupVn");
const btnPopupSave = document.getElementById("btnPopupSave");

const vocabChip = document.getElementById("vocabChip");
const chipCount = document.getElementById("chipCount");
const vocabPanel = document.getElementById("vocabPanel");
const panelCount = document.getElementById("panelCount");
const btnClosePanel = document.getElementById("btnClosePanel");
const btnExportVocab = document.getElementById("btnExportVocab");
const vocabList = document.getElementById("vocabList");

let savedVocab = [];
let currentLookupData = null;
const clientLookupCache = {};

// Right-click on selection -> open context popup
document.addEventListener("contextmenu", async (e) => {
  const selection = window.getSelection().toString().trim();
  if (!selection || selection.length > 50) {
    contextPopup.classList.remove("visible");
    return;
  }

  e.preventDefault();

  const nextStt = savedVocab.length + 1;
  const cleanWordKey = selection.toLowerCase();

  const posX = Math.min(e.clientX, window.innerWidth - 330);
  const posY = Math.min(e.clientY, window.innerHeight - 200);
  contextPopup.style.left = Math.max(10, posX) + "px";
  contextPopup.style.top = Math.max(10, posY) + "px";

  // Check client-side cache for instant display
  if (clientLookupCache[cleanWordKey]) {
    const data = clientLookupCache[cleanWordKey];
    currentLookupData = {
      stt: nextStt,
      word: data.word,
      phonetic: data.phonetic || data.pinyin || "",
      en: data.en,
      vn: data.vn,
    };
    popupStt.textContent = nextStt;
    popupWord.textContent = data.word;
    popupPhonetic.textContent = data.phonetic || data.pinyin || "";
    popupEn.textContent = data.en || "—";
    popupVn.textContent = data.vn || "—";
    btnPopupSave.disabled = false;
    contextPopup.classList.add("visible");
    return;
  }

  popupStt.textContent = nextStt;
  popupWord.textContent = selection;
  popupPhonetic.textContent = "";
  popupEn.textContent = "…";
  popupVn.textContent = "…";
  btnPopupSave.disabled = true;

  try {
    const res = await fetch("/api/lookup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: selection }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    const phonetic = data.phonetic || data.pinyin || "";
    clientLookupCache[cleanWordKey] = { ...data, phonetic };

    currentLookupData = {
      stt: nextStt,
      word: data.word || selection,
      phonetic: phonetic,
      en: data.en || "—",
      vn: data.vn || "—",
    };

    popupWord.textContent = data.word || selection;
    popupPhonetic.textContent = phonetic;
    popupEn.textContent = data.en || "—";
    popupVn.textContent = data.vn || "—";
    btnPopupSave.disabled = false;
    contextPopup.classList.add("visible");
  } catch (err) {
    popupEn.textContent = "Could not fetch definition.";
    popupVn.textContent = "Không thể tra từ.";
    contextPopup.classList.add("visible");
  }
});

// Close popup on outside click
document.addEventListener("click", (e) => {
  if (contextPopup && !contextPopup.contains(e.target)) {
    contextPopup.classList.remove("visible");
  }
});

btnPopupSave.addEventListener("click", () => {
  if (!currentLookupData) return;

  const exists = savedVocab.some((w) => w.word.toLowerCase() === currentLookupData.word.toLowerCase());
  if (!exists) {
    currentLookupData.stt = savedVocab.length + 1;
    savedVocab.push(currentLookupData);
    updateVocabUI();
  }

  contextPopup.classList.remove("visible");
});

// Render saved vocabulary list
function updateVocabUI() {
  const count = savedVocab.length;
  chipCount.textContent = count;
  panelCount.textContent = count;

  if (count === 0) {
    vocabList.innerHTML = '<div class="vocab-empty">No words saved yet. Highlight any word & right-click!</div>';
    return;
  }

  vocabList.innerHTML = "";
  savedVocab.forEach((item, idx) => {
    item.stt = idx + 1;
    const card = document.createElement("div");
    card.className = "vocab-card";
    card.innerHTML = `
      <button class="btn-del-vocab" data-index="${idx}" title="Remove word">✖</button>
      <div class="vocab-card-header">
        <span class="vocab-card-title">${item.stt}. ${item.word}</span>
        <span class="vocab-card-phonetic">${item.phonetic}</span>
      </div>
      <div class="vocab-card-line"><strong>EN:</strong> ${item.en}</div>
      <div class="vocab-card-line"><strong>VN:</strong> ${item.vn}</div>
    `;
    vocabList.appendChild(card);
  });

  vocabList.querySelectorAll(".btn-del-vocab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const index = parseInt(btn.dataset.index, 10);
      savedVocab.splice(index, 1);
      updateVocabUI();
    });
  });
}

// Toggle panel with floating chip
vocabChip.addEventListener("click", () => {
  vocabPanel.classList.toggle("open");
});

btnClosePanel.addEventListener("click", () => {
  vocabPanel.classList.remove("open");
});

// Save vocabulary to local file
btnExportVocab.addEventListener("click", async () => {
  if (savedVocab.length === 0) {
    alert("No words saved to export!");
    return;
  }

  try {
    btnExportVocab.disabled = true;
    btnExportVocab.textContent = "Saving…";

    const res = await fetch("/api/save-vocab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ words: savedVocab, folder_name: currentFolderName }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Save failed");

    alert(`Saved to local file:\n${data.filepath || data.path}`);
  } catch (err) {
    alert("Error saving file: " + err.message);
  } finally {
    btnExportVocab.disabled = false;
    btnExportVocab.textContent = "💾 Save to File";
  }
});

/* ── Persistence Settings ────────────────────────────────── */
async function loadInitialSettings() {
  let s = {};
  try {
    const res = await fetch("/api/settings");
    if (res.ok) s = await res.json();
  } catch (e) {}

  try {
    const local = JSON.parse(localStorage.getItem("user_tts_settings") || "{}");
    s = { ...s, ...local };
  } catch (e) {}

  if (s.hidden_pct !== undefined && pctSelect) {
    pctSelect.value = s.hidden_pct;
  }
  if (s.backward_sec !== undefined) {
    backwardSec = parseInt(s.backward_sec, 10);
    if (bwdVal) bwdVal.textContent = backwardSec;
  }
  if (s.forward_sec !== undefined) {
    forwardSec = parseInt(s.forward_sec, 10);
    if (fwdVal) fwdVal.textContent = forwardSec;
  }
  if (s.pace !== undefined && speedSlider) {
    const pace = parseFloat(s.pace);
    speedSlider.value = pace;
    const formatted = pace.toFixed(1) + "×";
    if (speedToggle) speedToggle.textContent = formatted;
    if (speedVal) speedVal.textContent = formatted;
    audioEl.playbackRate = pace;
  }
}

async function saveSetting(partial) {
  try {
    const local = JSON.parse(localStorage.getItem("user_tts_settings") || "{}");
    const updated = { ...local, ...partial };
    localStorage.setItem("user_tts_settings", JSON.stringify(updated));
  } catch (e) {}

  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(partial),
    });
  } catch (e) {}
}

/* ── Save Progress & Resume Feature ───────────────────────── */
const btnSaveProgress = document.getElementById("btnSaveProgress");
if (btnSaveProgress) {
  btnSaveProgress.addEventListener("click", async () => {
    if (!currentFolderName) {
      alert("No active lesson to save!");
      return;
    }

    const inputsObj = {};
    const inputs = dictationGrid.querySelectorAll("input");
    inputs.forEach((input) => {
      inputsObj[input.dataset.index] = input.value;
    });

    try {
      btnSaveProgress.disabled = true;
      btnSaveProgress.textContent = "Saving…";

      const res = await fetch("/api/save-progress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          folder_name: currentFolderName,
          raw_text: currentRawText,
          voice: voiceSelect ? voiceSelect.value : "",
          hidden_pct: pctSelect ? parseInt(pctSelect.value, 10) : 100,
          pace: speedSlider ? parseFloat(speedSlider.value) : 1.0,
          audio_time: audioEl ? audioEl.currentTime : 0,
          timer_seconds: timerSeconds,
          user_inputs: inputsObj,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to save progress");

      setStatus("Progress saved! Local resume script 'continue.command' generated in outputs/" + currentFolderName);
      alert("Progress saved successfully!\n\nYou can double-click 'continue.command' inside the lesson folder at any time to resume offline.");
    } catch (err) {
      alert("Error saving progress: " + err.message);
    } finally {
      btnSaveProgress.disabled = false;
      btnSaveProgress.textContent = "💾 Save Progress";
    }
  });
}

async function checkResumeParam() {
  const urlParams = new URLSearchParams(window.location.search);
  const resumeFolder = urlParams.get("resume");
  if (!resumeFolder) return;

  setStatus("Resuming lesson: " + resumeFolder + "…");
  try {
    const res = await fetch(`/api/resume-progress?folder=${encodeURIComponent(resumeFolder)}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Failed to load progress");
    }

    const data = await res.json();
    const progress = data.progress || {};
    const metadata = data.metadata || {};

    currentFolderName = data.folder_name || resumeFolder;
    currentRawText = progress.raw_text || metadata.text || "";
    textInput.value = currentRawText;

    if (progress.voice && voiceSelect) voiceSelect.value = progress.voice;
    if (metadata.word_boundaries) wordBoundaries = metadata.word_boundaries;
    if (metadata.pinyin_map) globalPinyinMap = metadata.pinyin_map;

    audioEl.src = data.audio_url;
    audioEl.load();

    if (progress.pace && speedSlider) {
      const pace = parseFloat(progress.pace);
      speedSlider.value = pace;
      const formatted = pace.toFixed(1) + "×";
      if (speedToggle) speedToggle.textContent = formatted;
      if (speedVal) speedVal.textContent = formatted;
      audioEl.playbackRate = pace;
    }

    if (progress.hidden_pct && pctSelect) {
      pctSelect.value = progress.hidden_pct;
    }

    buildTrackingWords();
    buildDictation(currentRawText);

    if (progress.user_inputs) {
      const inputs = dictationGrid.querySelectorAll("input");
      inputs.forEach((input) => {
        const idx = input.dataset.index;
        if (progress.user_inputs[idx] !== undefined) {
          input.value = progress.user_inputs[idx];
        }
      });
    }

    if (progress.timer_seconds !== undefined) {
      timerSeconds = parseInt(progress.timer_seconds, 10) || 0;
      updateTimerDisplay();
    }

    if (progress.audio_time) {
      const targetTime = parseFloat(progress.audio_time);
      const setAudioTime = () => {
        if (targetTime > 0 && targetTime < audioEl.duration) {
          audioEl.currentTime = targetTime;
        }
      };
      if (audioEl.readyState >= 1) {
        setAudioTime();
      } else {
        audioEl.addEventListener("loadedmetadata", setAudioTime, { once: true });
      }
    }

    trackingSection.classList.add("visible");
    audioBar.classList.add("visible");
    dictationSection.classList.add("visible");
    if (btnApplyPct) btnApplyPct.disabled = false;
    if (pctSelect) pctSelect.disabled = false;

    setStatus("Lesson resumed! All typed answers and audio position restored.");
  } catch (err) {
    setStatus("Error resuming lesson: " + err.message, true);
  }
}

/* ── Manual Study Timer ──────────────────────────────────── */
let timerSeconds = 0;
let timerInterval = null;
let isTimerRunning = false;

const timerDisplay = document.getElementById("timerDisplay");
const btnTimerToggle = document.getElementById("btnTimerToggle");

function formatHHMMSS(totalSec) {
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

function updateTimerDisplay() {
  if (timerDisplay) {
    timerDisplay.textContent = "⏱ " + formatHHMMSS(timerSeconds);
  }
}

function toggleManualTimer() {
  if (isTimerRunning) {
    clearInterval(timerInterval);
    timerInterval = null;
    isTimerRunning = false;
    if (btnTimerToggle) {
      btnTimerToggle.textContent = "⏱ Start";
      btnTimerToggle.classList.remove("running");
    }
  } else {
    isTimerRunning = true;
    if (btnTimerToggle) {
      btnTimerToggle.textContent = "⏱ Pause";
      btnTimerToggle.classList.add("running");
    }
    timerInterval = setInterval(() => {
      timerSeconds++;
      updateTimerDisplay();
    }, 1000);
  }
}

if (btnTimerToggle) {
  btnTimerToggle.addEventListener("click", toggleManualTimer);
}

/* ── Init ────────────────────────────────────────────────── */
async function init() {
  await loadVoices();
  await loadInitialSettings();
  await checkResumeParam();
}

init();
