const dropArea = document.getElementById('drop-area');
const fileElem = document.getElementById('fileElem');

dropArea.addEventListener('click', () => fileElem.click());

fileElem.addEventListener('change', () => {
  for (let file of fileElem.files) {
    uploadFile(file);
  }
});

dropArea.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropArea.style.background = "#f0f0f0";
});

dropArea.addEventListener('dragleave', () => {
  dropArea.style.background = "white";
});

dropArea.addEventListener('drop', (e) => {
  e.preventDefault();
  for (let file of e.dataTransfer.files) {
    uploadFile(file);
  }
});

function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  fetch("/upload", {
    method: "POST",
    body: formData
  }).then(() => location.reload());
}
