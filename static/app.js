const themeEl = document.getElementById("theme");
const characterEl = document.getElementById("character");
const jobIdEl = document.getElementById("jobId");
const goBtn = document.getElementById("go");
const resumeBtn = document.getElementById("resume");
const progressPanel = document.getElementById("progress-panel");
const resultPanel = document.getElementById("result-panel");
const statusEl = document.getElementById("status");
const logsEl = document.getElementById("logs");
const galleryEl = document.getElementById("gallery");
const extrasEl = document.getElementById("extras");
const zipLink = document.getElementById("zip-link");
const subtitleEl = document.getElementById("subtitle");
const modeHintEl = document.getElementById("mode-hint");

let pollTimer = null;

async function init() {
  const res = await fetch("/api/defaults");
  const data = await res.json();
  characterEl.value = data.character || "";
  const count = data.count || 8;
  if (data.i2v_enabled) {
    subtitleEl.textContent = `输入主题 → AI 规划 ${count} 张 → 静图 / 动图 / 投稿配套素材一键产出`;
    modeHintEl.textContent = "完整流程含图生视频，通常需要较长时间，请保持页面打开。";
  } else {
    subtitleEl.textContent = `输入主题 → AI 规划 ${count} 张 → 静图 PNG / 投稿配套素材（未配置图生视频）`;
    modeHintEl.textContent = "当前未配置 I2V_MODEL，将只生成静图表情包。配上图生视频模型后可产出 GIF。";
  }
  const params = new URLSearchParams(location.search);
  const job = params.get("job");
  if (job) jobIdEl.value = job;
}

function setBusy(busy) {
  goBtn.disabled = busy;
  resumeBtn.disabled = busy;
}

function appendLog(entry) {
  const li = document.createElement("li");
  const msg = entry.message || entry.stage;
  li.textContent = msg;
  logsEl.prepend(li);
}

function renderResult(jobId, manifest) {
  resultPanel.hidden = false;
  zipLink.href = `/outputs/${jobId}/${manifest.zip}`;
  zipLink.download = manifest.zip;

  galleryEl.innerHTML = "";
  for (const s of manifest.stickers || []) {
    const file = s.gif || s.image;
    if (!file) continue;
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <img src="/outputs/${jobId}/${file}" alt="${s.label || s.id}" />
      <div class="cap">${s.caption || s.label || s.id}</div>
    `;
    galleryEl.appendChild(card);
  }

  const f = manifest.files || {};
  extrasEl.innerHTML = `
    <figure>
      <img src="/outputs/${jobId}/${f.banner}" alt="横幅" />
      <figcaption>详情页横幅 750×400</figcaption>
    </figure>
    <figure>
      <img src="/outputs/${jobId}/${f.cover}" alt="封面" />
      <figcaption>封面 240×240</figcaption>
    </figure>
    <figure>
      <img src="/outputs/${jobId}/${f.icon}" alt="图标" />
      <figcaption>聊天页图标 50×50</figcaption>
    </figure>
  `;
}

async function poll(jobId) {
  const res = await fetch(`/api/jobs/${jobId}`);
  const job = await res.json();
  if (!res.ok) {
    statusEl.textContent = job.error || "任务查询失败";
    setBusy(false);
    clearInterval(pollTimer);
    return;
  }

  const logs = job.logs || [];
  logsEl.innerHTML = "";
  for (const entry of [...logs].reverse()) appendLog(entry);

  const last = logs[logs.length - 1];
  statusEl.textContent = last?.message || job.status;

  if (job.status === "done" && job.manifest) {
    clearInterval(pollTimer);
    setBusy(false);
    statusEl.textContent = "全部完成";
    renderResult(jobId, job.manifest);
  } else if (job.status === "error") {
    clearInterval(pollTimer);
    setBusy(false);
    statusEl.textContent = `失败：${job.error || "未知错误"}`;
  }
}

function startPolling(jobId) {
  jobIdEl.value = jobId;
  history.replaceState(null, "", `?job=${encodeURIComponent(jobId)}`);
  progressPanel.hidden = false;
  resultPanel.hidden = true;
  logsEl.innerHTML = "";
  statusEl.textContent = "任务已开始";
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => poll(jobId), 2000);
  poll(jobId);
}

goBtn.addEventListener("click", async () => {
  const theme = themeEl.value.trim();
  if (!theme) {
    themeEl.focus();
    return;
  }

  setBusy(true);
  statusEl.textContent = "提交任务…";
  progressPanel.hidden = false;

  const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      theme,
      character: characterEl.value.trim(),
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    statusEl.textContent = data.error || "提交失败";
    setBusy(false);
    return;
  }
  startPolling(data.job_id);
});

resumeBtn.addEventListener("click", async () => {
  const jobId = jobIdEl.value.trim();
  if (!jobId) {
    jobIdEl.focus();
    return;
  }

  setBusy(true);
  statusEl.textContent = "续跑提交中…";
  progressPanel.hidden = false;

  const res = await fetch(`/api/resume/${encodeURIComponent(jobId)}`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    statusEl.textContent = data.error || "续跑失败";
    setBusy(false);
    return;
  }
  startPolling(data.job_id);
});

init();
