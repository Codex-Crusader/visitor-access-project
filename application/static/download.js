// Shared by the gate desk and the admin page, which load it before their own
// script. Both download the same visit log.

// Hands a fetched file to the browser to save. The server names the file
// with the date, as visits-2026-09-29.csv.
async function saveFile(r) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  const named = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
  a.download = named ? named[1] : "visits.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}
