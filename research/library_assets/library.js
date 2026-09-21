(function () {
  "use strict";
  const form = document.querySelector("[data-filter-form]");
  if (!form) return;
  form.querySelectorAll("select").forEach((select) => {
    select.addEventListener("change", () => form.requestSubmit());
  });
  const search = form.querySelector('input[name="q"]');
  if (search) {
    search.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && search.value) {
        search.value = "";
        form.requestSubmit();
      }
    });
  }
})();
