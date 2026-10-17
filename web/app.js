(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const state = {
    token: localStorage.getItem("leica.token") || "",
    config: null,
    file: null,
    fileURL: null,
    originalURL: null,
    resultURL: null,
    jobId: null,
    busy: false,
    mode: "COLOR_AND_BLUR",
    aperture: 2.0,
    output: "SIZE_2048",
    focus: null,
    natural: null,
    pollTimer: null,
    split: 50,
  };

  class AuthError extends Error {}

  const els = {
    dropzone: $("#dropzone"),
    emptyState: $("#empty-state"),
    fileInput: $("#file-input"),
    compare: $("#compare"),
    imgOriginal: $("#img-original"),
    imgResult: $("#img-result"),
    divider: $("#divider"),
    focusMarker: $("#focus-marker"),
    compareControls: $("#compare-controls"),
    compareRange: $("#compare-range"),
    splitValue: $("#split-value"),
    stageDot: $("#stage-dot"),
    stageText: $("#stage-text"),
    progressBar: $("#progress-bar"),
    pickAgain: $("#pick-again"),
    modeButtons: $("#mode-buttons"),
    modeHint: $("#mode-hint"),
    apertureBlock: $("#aperture-block"),
    apertureButtons: $("#aperture-buttons"),
    outputBlock: $("#output-block"),
    outputButtons: $("#output-buttons"),
    focusBlock: $("#focus-block"),
    focusHint: $("#focus-hint"),
    generate: $("#generate"),
    download: $("#download"),
    meta: $("#meta"),
    reason: $("#reason"),
    timings: $("#timings"),
    error: $("#error"),
    tokenChip: $("#token-chip"),
    tokenStatus: $("#token-status"),
    modal: $("#token-modal"),
    tokenInput: $("#token-input"),
    tokenError: $("#token-error"),
    tokenSubmit: $("#token-submit"),
    queueInfo: $("#queue-info"),
    viewer: $(".viewer"),
  };

  const TIMING_LABELS = {
    total: "总计",
    read: "读取",
    depth: "深度",
    color: "上色",
    fuse: "融合",
    render: "虚化",
    encode: "编码",
  };

  function modeInfo(name) {
    return (state.config?.modes || []).find((m) => m.name === name) || {
      name,
      label: name,
      color: true,
      blur: true,
    };
  }

  function setStage(text, kind = "") {
    els.stageText.textContent = text;
    els.stageDot.className = "stage-dot" + (kind ? " " + kind : "");
  }

  function setProgress(value) {
    const v = Math.min(1, Math.max(0, Number(value) || 0));
    els.progressBar.style.width = `${v * 100}%`;
  }

  function showError(message) {
    els.error.textContent = message;
    els.error.classList.remove("hidden");
  }

  function clearError() {
    els.error.textContent = "";
    els.error.classList.add("hidden");
  }

  function setTokenChip(ok) {
    els.tokenChip.classList.toggle("ok", ok);
    els.tokenStatus.textContent = ok ? "已连接" : "未授权";
  }

  function openTokenModal(message = "") {
    els.modal.classList.remove("hidden");
    els.tokenError.textContent = message;
    els.tokenError.classList.toggle("hidden", !message);
    els.tokenInput.value = "";
    setTimeout(() => els.tokenInput.focus(), 60);
  }

  function closeTokenModal() {
    els.modal.classList.add("hidden");
    els.tokenError.classList.add("hidden");
  }

  async function getError(res) {
    try {
      const data = await res.json();
      return data.detail || data.error || JSON.stringify(data);
    } catch {
      return res.statusText || `HTTP ${res.status}`;
    }
  }

  async function api(path, opts = {}) {
    const headers = new Headers(opts.headers || {});
    if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) {
      setTokenChip(false);
      openTokenModal("访问令牌无效，请重新输入");
      throw new AuthError("unauthorized");
    }
    return res;
  }

  async function validateToken(token) {
    const res = await fetch("/api/jobs/__ping__", {
      headers: { Authorization: `Bearer ${token}` },
    });
    return res.status === 404;
  }

  async function submitToken() {
    const token = els.tokenInput.value.trim();
    if (!token) {
      els.tokenError.textContent = "请输入访问令牌";
      els.tokenError.classList.remove("hidden");
      return;
    }
    els.tokenSubmit.disabled = true;
    els.tokenError.classList.add("hidden");
    try {
      const ok = await validateToken(token);
      if (!ok) {
        els.tokenError.textContent = "令牌无效，请查看启动日志或 data/token.txt";
        els.tokenError.classList.remove("hidden");
        return;
      }
      state.token = token;
      localStorage.setItem("leica.token", token);
      setTokenChip(true);
      closeTokenModal();
      clearError();
      updateGenerate();
    } catch {
      els.tokenError.textContent = "无法连接后端服务";
      els.tokenError.classList.remove("hidden");
    } finally {
      els.tokenSubmit.disabled = false;
    }
  }

  // ---------------------------------------------------------------- config
  function buildControls() {
    const cfg = state.config;
    els.modeButtons.innerHTML = "";
    for (const m of cfg.modes) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = m.label;
      b.dataset.name = m.name;
      b.addEventListener("click", () => {
        if (!state.busy) setMode(m.name);
      });
      els.modeButtons.appendChild(b);
    }

    els.apertureButtons.innerHTML = "";
    for (const a of cfg.apertures) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = a.label;
      b.dataset.value = String(a.value);
      b.addEventListener("click", () => {
        if (!state.busy) setAperture(a.value);
      });
      els.apertureButtons.appendChild(b);
    }

    els.outputButtons.innerHTML = "";
    for (const o of cfg.output_sizes) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = o.label;
      b.dataset.name = o.name;
      b.addEventListener("click", () => {
        if (!state.busy) setOutput(o.name);
      });
      els.outputButtons.appendChild(b);
    }
  }

  function setMode(name) {
    state.mode = name;
    const info = modeInfo(name);
    const blur = !!info.blur;
    const color = !!info.color;

    [...els.modeButtons.children].forEach((b) =>
      b.classList.toggle("active", b.dataset.name === name)
    );
    [...els.apertureButtons.children].forEach((b) => (b.disabled = !blur));
    [...els.outputButtons.children].forEach((b) => (b.disabled = !blur));
    els.apertureBlock.classList.toggle("muted-block", !blur);
    els.outputBlock.classList.toggle("muted-block", !blur);
    els.focusBlock.classList.toggle("muted-block", !blur);
    els.compare.style.cursor = blur ? "crosshair" : "default";

    if (blur) {
      els.focusHint.textContent = state.focus
        ? "焦点已确定 · 点击其他位置可重选"
        : "在原图上轻点，选择要对焦的位置";
    } else {
      els.focusHint.textContent = "仅调色模式不需要对焦点";
    }
    els.focusMarker.classList.toggle("hidden", !(blur && state.focus));

    if (name === "COLOR_ONLY") {
      els.modeHint.textContent =
        "仅色彩迁移，保留原图分辨率；不加载深度/虚化模型。";
    } else if (name === "BLUR_ONLY") {
      els.modeHint.textContent =
        "保留原照片色彩，使用深度与虚化模型；请先选择焦点。";
    } else {
      els.modeHint.textContent = "完整链路：深度 → 色彩迁移 → 融合 → 虚化。";
    }
    updateGenerate();
  }

  function setAperture(value) {
    state.aperture = Number(value);
    [...els.apertureButtons.children].forEach((b) =>
      b.classList.toggle("active", Number(b.dataset.value) === state.aperture)
    );
  }

  function setOutput(name) {
    state.output = name;
    [...els.outputButtons.children].forEach((b) =>
      b.classList.toggle("active", b.dataset.name === name)
    );
  }

  function updateGenerate() {
    const blur = !!modeInfo(state.mode).blur;
    const needsFocus = blur && !state.focus;
    els.generate.disabled =
      !state.file || state.busy || !state.token || needsFocus;
    els.generate.textContent = state.busy ? "处理中…" : "生成成片";
    els.pickAgain.classList.toggle("hidden", !state.file);
  }

  // ---------------------------------------------------------------- files
  function revoke(url) {
    if (url) URL.revokeObjectURL(url);
  }

  function resetResultVisuals() {
    els.imgResult.classList.add("hidden");
    els.divider.classList.add("hidden");
    els.compareControls.classList.add("hidden");
    els.download.classList.add("hidden");
    els.meta.classList.add("hidden");
    els.imgResult.removeAttribute("src");
    revoke(state.resultURL);
    revoke(state.originalURL);
    state.resultURL = null;
    state.originalURL = null;
    setSplit(50);
  }

  function handleFile(file) {
    if (!file) return;
    const isImage =
      file.type.startsWith("image/") ||
      /\.(jpe?g|png|webp|heic|heif|bmp|tiff?|avif)$/i.test(file.name || "");
    if (!isImage) {
      showError("请选择图片文件");
      return;
    }
    const limitMb = state.config?.limits?.max_upload_mb || 30;
    if (file.size > limitMb * 1024 * 1024) {
      showError(`文件超过 ${limitMb} MB 限制`);
      return;
    }

    clearError();
    clearTimeout(state.pollTimer);
    state.busy = false;
    state.file = file;
    state.jobId = null;
    state.focus = null;
    state.natural = null;
    revoke(state.fileURL);
    revoke(state.resultURL);
    revoke(state.originalURL);
    state.resultURL = null;
    state.originalURL = null;
    state.fileURL = URL.createObjectURL(file);

    els.emptyState.classList.add("hidden");
    els.compare.classList.remove("hidden");
    els.dropzone.classList.add("has-image");
    els.focusMarker.classList.add("hidden");
    resetResultVisuals();
    setProgress(0);
    setStage("已选择照片 · 请选择处理模式和焦点", "");

    els.imgOriginal.onload = () => {
      state.natural = {
        w: els.imgOriginal.naturalWidth || 3,
        h: els.imgOriginal.naturalHeight || 2,
      };
      layoutCompare();
      const cfg = state.config?.limits;
      if (cfg && state.natural.w * state.natural.h > cfg.max_pixels) {
        showError("照片像素数超过服务端限制，生成会被拒绝");
      }
    };
    els.imgOriginal.onerror = () => {
      state.natural = { w: 3, h: 2 };
      layoutCompare();
      setStage("此格式浏览器无法直接预览；生成后显示服务端预览", "");
    };
    els.imgOriginal.src = state.fileURL;
    els.imgOriginal.classList.remove("hidden");
    updateGenerate();
  }

  function pickFile() {
    if (state.busy) return;
    els.fileInput.value = "";
    els.fileInput.click();
  }

  // ---------------------------------------------------------------- focus
  function setFocusFromEvent(event) {
    if (!state.file || state.busy) return;
    if (!modeInfo(state.mode).blur) return;
    const rect = els.compare.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    state.focus = { x, y };
    els.focusMarker.style.left = `${x * 100}%`;
    els.focusMarker.style.top = `${y * 100}%`;
    els.focusMarker.classList.remove("hidden");
    els.focusHint.textContent = "焦点已确定 · 点击其他位置可重选";
    updateGenerate();
  }

  // ---------------------------------------------------------------- layout
  function layoutCompare() {
    if (!state.natural) return;
    const nw = state.natural.w;
    const nh = state.natural.h;
    const pad = 24;
    const boxW = Math.max(240, els.dropzone.clientWidth - pad);
    const boxH = Math.max(
      240,
      Math.min(window.innerHeight * 0.66, els.dropzone.clientHeight - pad || 600)
    );
    const scale = Math.min(boxW / nw, boxH / nh, 1);
    els.compare.style.width = `${Math.round(nw * scale)}px`;
    els.compare.style.height = `${Math.round(nh * scale)}px`;
  }

  function setSplit(value) {
    state.split = Math.min(100, Math.max(0, Number(value)));
    els.compare.style.setProperty("--split", `${state.split}%`);
    els.divider.style.left = `${state.split}%`;
    els.compareRange.value = String(Math.round(state.split));
    els.splitValue.textContent = `${Math.round(state.split)}%`;
  }

  // ---------------------------------------------------------------- jobs
  async function generate() {
    clearError();
    if (!state.token) {
      openTokenModal();
      return;
    }
    if (!state.file || state.busy) return;
    const info = modeInfo(state.mode);
    if (info.blur && !state.focus) {
      showError("请先在原照片上点击焦点");
      return;
    }

    state.busy = true;
    updateGenerate();
    resetResultVisuals();
    setProgress(0.02);
    setStage("正在上传照片…", "active");

    const form = new FormData();
    form.append("file", state.file, state.file.name || "photo");
    form.append("mode", state.mode);
    form.append("aperture", String(state.aperture));
    form.append("output_size", state.output);
    if (info.blur && state.focus) {
      form.append("focus_x", String(state.focus.x));
      form.append("focus_y", String(state.focus.y));
    }

    try {
      const res = await api("/api/jobs", { method: "POST", body: form });
      if (!res.ok) throw new Error(await getError(res));
      const job = await res.json();
      state.jobId = job.id;
      pollJob(job.id);
    } catch (err) {
      if (err instanceof AuthError) {
        state.busy = false;
        updateGenerate();
        return;
      }
      fail(err.message || "上传失败");
    }
  }

  function pollJob(jobId) {
    clearTimeout(state.pollTimer);
    const tick = async () => {
      try {
        const res = await api(`/api/jobs/${jobId}`);
        if (!res.ok) throw new Error(await getError(res));
        const job = await res.json();
        setProgress(job.progress || 0);
        if (job.status === "done") {
          await finishJob(job);
          return;
        }
        if (job.status === "error") {
          fail(job.error || "处理失败");
          return;
        }
        setStage(
          job.message || "处理中",
          job.status === "processing" ? "active" : ""
        );
        state.pollTimer = setTimeout(tick, 1000);
      } catch (err) {
        if (err instanceof AuthError) {
          state.busy = false;
          updateGenerate();
          return;
        }
        fail(err.message || "任务查询失败");
      }
    };
    tick();
  }

  async function finishJob(job) {
    try {
      const [rres, ores] = await Promise.all([
        api(job.result_url),
        api(job.original_url),
      ]);
      if (!rres.ok) throw new Error(await getError(rres));
      if (!ores.ok) throw new Error(await getError(ores));
      const [rblob, oblob] = await Promise.all([rres.blob(), ores.blob()]);

      revoke(state.resultURL);
      revoke(state.originalURL);
      state.resultURL = URL.createObjectURL(rblob);
      state.originalURL = URL.createObjectURL(oblob);

      els.imgOriginal.onload = () => {
        state.natural = {
          w: els.imgOriginal.naturalWidth || 3,
          h: els.imgOriginal.naturalHeight || 2,
        };
        layoutCompare();
      };
      els.imgOriginal.onerror = () => {};
      els.imgOriginal.src = state.originalURL;
      els.imgOriginal.classList.remove("hidden");
      els.imgResult.src = state.resultURL;
      els.imgResult.classList.remove("hidden");
      els.divider.classList.remove("hidden");
      els.compareControls.classList.remove("hidden");
      els.download.classList.remove("hidden");
      setSplit(50);
      setProgress(1);
      const total = Number(job.timings?.total || 0);
      setStage(
        total > 0 ? `生成完成 · 用时 ${total.toFixed(1)} 秒` : "生成完成",
        "done"
      );
      showMeta(job);
      state.busy = false;
      updateGenerate();
    } catch (err) {
      if (err instanceof AuthError) {
        state.busy = false;
        updateGenerate();
        return;
      }
      fail(err.message || "结果下载失败");
    }
  }

  function showMeta(job) {
    els.meta.classList.remove("hidden");
    els.reason.textContent = job.reason || "";
    els.timings.innerHTML = "";
    const rows = [];
    if (job.width && job.height) {
      rows.push(["成片尺寸", `${job.width} × ${job.height}`]);
      rows.push([
        "模式 / 光圈",
        `${modeInfo(job.mode).label} · f/${Number(job.aperture).toFixed(
          job.aperture === 0.95 ? 2 : 1
        )}`,
      ]);
      if (job.focus !== null && job.focus !== undefined) {
        rows.push(["焦点深度", Number(job.focus).toFixed(4)]);
      }
    }
    for (const [key, label] of Object.entries(TIMING_LABELS)) {
      const v = job.timings?.[key];
      if (typeof v === "number") rows.push([label, `${v.toFixed(2)} s`]);
    }
    for (const [label, value] of rows) {
      const div = document.createElement("div");
      const span = document.createElement("span");
      span.textContent = label;
      const b = document.createElement("b");
      b.textContent = value;
      div.append(span, b);
      els.timings.appendChild(div);
    }
  }

  function fail(message) {
    clearTimeout(state.pollTimer);
    state.busy = false;
    updateGenerate();
    setProgress(1);
    setStage("处理失败", "error");
    showError(message || "处理失败");
  }

  // ---------------------------------------------------------------- misc
  async function updateQueueInfo() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) return;
      const data = await res.json();
      const limit = state.config?.limits?.queue ?? 3;
      els.queueInfo.textContent = data.models
        ? `队列 ${data.queue}/${limit}`
        : "模型文件缺失";
    } catch {
      els.queueInfo.textContent = "服务不可达";
    }
  }

  async function loadConfig() {
    const res = await fetch("/api/config");
    if (!res.ok) throw new Error("无法读取服务配置");
    state.config = await res.json();
    buildControls();
    setMode(state.config.defaults?.mode || "COLOR_AND_BLUR");
    setAperture(state.config.defaults?.aperture ?? 2.0);
    setOutput(state.config.defaults?.output_size || "SIZE_2048");
  }

  // ---------------------------------------------------------------- events
  function bind() {
    els.dropzone.addEventListener("click", (event) => {
      if (event.target.closest("#compare")) return;
      if (!state.file) pickFile();
    });
    els.pickAgain.addEventListener("click", (event) => {
      event.stopPropagation();
      pickFile();
    });
    els.fileInput.addEventListener("change", () => {
      if (els.fileInput.files?.[0]) handleFile(els.fileInput.files[0]);
    });
    ["dragenter", "dragover"].forEach((name) => {
      els.dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        event.stopPropagation();
        els.dropzone.classList.add("dragover");
      });
    });
    ["dragleave", "dragend", "drop"].forEach((name) => {
      els.dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        event.stopPropagation();
        els.dropzone.classList.remove("dragover");
      });
    });
    els.dropzone.addEventListener("drop", (event) => {
      const file = event.dataTransfer?.files?.[0];
      if (file) handleFile(file);
    });
    document.addEventListener("paste", (event) => {
      const item = [...(event.clipboardData?.items || [])].find((i) =>
        i.type.startsWith("image/")
      );
      if (item) {
        const file = item.getAsFile();
        if (file) handleFile(file);
      }
    });

    els.compare.addEventListener("click", setFocusFromEvent);
    els.generate.addEventListener("click", generate);
    els.compareRange.addEventListener("input", (event) =>
      setSplit(event.target.value)
    );
    els.download.addEventListener("click", () => {
      if (!state.resultURL) return;
      const a = document.createElement("a");
      a.href = state.resultURL;
      a.download = `传奇一瞬-${state.jobId?.slice(0, 8) || "result"}.png`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    });

    els.tokenChip.addEventListener("click", () => openTokenModal(""));
    els.tokenSubmit.addEventListener("click", submitToken);
    els.tokenInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") submitToken();
    });
    els.modal.addEventListener("click", (event) => {
      if (event.target === els.modal && state.token) closeTokenModal();
    });

    window.addEventListener("resize", () => layoutCompare());
    window.addEventListener("beforeunload", () => {
      revoke(state.fileURL);
      revoke(state.originalURL);
      revoke(state.resultURL);
    });
  }

  async function init() {
    bind();
    setSplit(50);
    try {
      await loadConfig();
    } catch (err) {
      showError("无法连接后端服务，请确认服务已启动");
    }
    if (state.token) {
      try {
        if (await validateToken(state.token)) {
          setTokenChip(true);
        } else {
          state.token = "";
          localStorage.removeItem("leica.token");
          setTokenChip(false);
          openTokenModal("令牌已失效，请重新输入");
        }
      } catch {
        openTokenModal("无法验证令牌");
      }
    } else {
      setTokenChip(false);
      openTokenModal();
    }
    updateGenerate();
    updateQueueInfo();
    setInterval(updateQueueInfo, 15000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
