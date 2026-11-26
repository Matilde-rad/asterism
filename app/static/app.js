const $ = (id) => document.getElementById(id);
const esc = (t) => String(t).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
const CATALOG_ONLY = new Set(["hd", "tycho2", "tycho"]);
let photoImg = null;
let result = null;

$("file").addEventListener("change", () => {
  const f = $("file").files[0];
  if (!f) return;
  $("drop-text").innerHTML = `📷 ${f.name}`;
  $("go").disabled = false;
  photoImg = new Image();
  photoImg.src = URL.createObjectURL(f);
});

$("go").addEventListener("click", async () => {
  const f = $("file").files[0];
  if (!f) return;
  const form = new FormData();
  form.append("file", f);
  form.append("utc_offset_hours", $("offset").value || "0");
  if ($("lat").value) form.append("lat", $("lat").value);
  if ($("lon").value) form.append("lon", $("lon").value);
  $("go").disabled = true;
  setStatus("Uploading…");
  try {
    const r = await fetch("/api/solve", { method: "POST", body: form });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    poll((await r.json()).id);
  } catch (e) {
    setStatus(e.message, true);
    $("go").disabled = false;
  }
});

const LABELS = {
  received: "Received…", uploading: "Sending to the star matcher…",
  queued: "Waiting in the solver queue…", solving: "Matching star patterns ✦ (can take a minute)",
};

async function poll(id) {
  const r = await fetch(`/api/solve/${id}`);
  const job = await r.json();
  if (job.status === "done") { setStatus("Solved!"); result = job.result; render(); $("go").disabled = false; return; }
  if (job.status === "failed") { setStatus(job.error || "Something went wrong", true); $("go").disabled = false; return; }
  setStatus(LABELS[job.status] || job.status);
  setTimeout(() => poll(id), 3000);
}

function setStatus(text, isError = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", isError);
}

function visibleObjects() {
  const showCatalog = $("show-catalog").checked;
  return result.objects.filter((o) => showCatalog || !CATALOG_ONLY.has(o.type));
}

function render() {
  $("result-card").classList.remove("hidden");
  const draw = () => {
    const c = $("sky"), ctx = c.getContext("2d");
    c.width = photoImg.naturalWidth; c.height = photoImg.naturalHeight;
    ctx.drawImage(photoImg, 0, 0);
    const s = Math.max(1, Math.max(c.width, c.height) / 1000); // keep labels readable on big photos
    ctx.font = `${Math.round(18 * s)}px system-ui, sans-serif`;
    for (const o of visibleObjects()) {
      if (o.x == null) continue;
      const r = Math.max(o.radius || 0, 10 * s);
      ctx.strokeStyle = "#c9cff2"; ctx.lineWidth = 2 * s;
      ctx.beginPath(); ctx.arc(o.x, o.y, r, 0, Math.PI * 2); ctx.stroke();
      const label = o.names[0] || "?";
      ctx.lineWidth = 4 * s; ctx.strokeStyle = "#04060f";
      ctx.strokeText(label, o.x + r + 4 * s, o.y + 6 * s);
      ctx.fillStyle = "#ffffff";
      ctx.fillText(label, o.x + r + 4 * s, o.y + 6 * s);
    }
  };
  photoImg.complete ? draw() : (photoImg.onload = draw);

  const facts = [];
  const c = result.center;
  if (c.ra_deg != null) facts.push(["Centre (RA / Dec)", `${c.ra_deg.toFixed(2)}° / ${c.dec_deg.toFixed(2)}°`]);
  if (result.field_radius_deg != null) facts.push(["Field of view", `≈ ${(result.field_radius_deg * 2).toFixed(1)}° across`]);
  if (result.orientation_deg != null) facts.push(["Camera tilt", `${result.orientation_deg.toFixed(1)}°`]);
  if (result.facing) facts.push(["You were facing", `${result.facing.compass}, ${result.facing.altitude_deg}° up`]);
  if (result.taken_at) facts.push(["Taken (UTC)", new Date(result.taken_at).toUTCString()]);
  $("facts").innerHTML = facts.map(([k, v]) => `<div class="fact"><b>${k}</b>${esc(v)}</div>`).join("");

  $("objects").innerHTML = visibleObjects()
    .map((o) => `<li>${esc(o.names.join(" · "))}</li>`).join("") || "<li>No named objects found</li>";
}

$("show-catalog").addEventListener("change", () => result && render());
