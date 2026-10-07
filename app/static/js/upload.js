"use strict";
const uploadForm = document.getElementById("upload-form");
if (uploadForm) {
  const file = document.getElementById("document-file");
  const selection = document.getElementById("upload-selection");
  const clear = document.getElementById("clear-upload");
  const progress = document.getElementById("upload-progress");
  const send = document.getElementById("send-upload");
  const update = () => {
    const selected = file.files[0];
    selection.textContent = selected ? `Selecionado: ${selected.name} · ${(selected.size / 1024 / 1024).toFixed(2)} MB` : "Nenhum arquivo selecionado.";
    clear.hidden = !selected;
    file.setCustomValidity(selected && selected.size > 15 * 1024 * 1024 ? "Arquivo acima de 15 MB." : "");
  };
  file.addEventListener("change", update);
  clear.addEventListener("click", () => { file.value = ""; update(); file.focus(); });
  uploadForm.addEventListener("submit", () => {
    send.disabled = true;
    clear.disabled = true;
    progress.textContent = "Enviando documento para validação. Aguarde…";
  });
}
if (document.querySelector("[data-refresh-upload]")) {
  window.setTimeout(() => window.location.reload(), 5000);
}
