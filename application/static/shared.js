// Shared by the gate desk and the admin page, which load it before their own script.

// Saves a fetched file, named by the server, such as visits-2026-09-29.csv.
async function saveFile(r) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  const named = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
  a.download = named ? named[1] : "visits.csv";
  a.click();
  // Later, not at once: a second save right after can lose the first file in some browsers.
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  return a.download;
}

// [ok, answer] for a request to send a key. A lost connection is not ok.
async function askForKey(which) {
  try {
    const r = await fetch(`/api/forgot-key/${which}`, {method: "POST"});
    const data = await r.json().catch(() => ({}));
    return [r.ok, r.ok ? data : {error: data.error || `Could not send the key (${r.status})`}];
  } catch (err) {
    return [false, {error: err.message}];
  }
}
