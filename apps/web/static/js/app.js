/*
 * Progressive enhancement only. The interface is complete without this file.
 *
 * Two behaviours, both of which improve an interaction that already works:
 * moving focus to an error summary when one is present, and keeping a count of
 * selected medications beside the fieldset legend. Neither changes what the
 * page says, neither fetches anything, and neither is required for any
 * assertion the accessibility tests make - those parse the server-rendered
 * HTML, which is what a reader with JavaScript disabled receives.
 *
 * There is no fetch, no XMLHttpRequest, no WebSocket, no eval, no innerHTML
 * assignment from data, and no third-party library. The content-security
 * policy forbids connecting anywhere, so a network call added here would fail
 * rather than succeed quietly.
 */
(function () {
  "use strict";

  function focusErrorSummary() {
    var summary = document.getElementById("error-summary");
    if (summary && typeof summary.focus === "function") {
      summary.focus();
    }
  }

  function announceSelectionCount() {
    var fieldsets = document.querySelectorAll(".assess-form fieldset");
    Array.prototype.forEach.call(fieldsets, function (fieldset) {
      var boxes = fieldset.querySelectorAll('input[type="checkbox"]');
      var legend = fieldset.querySelector("legend");
      if (!legend || boxes.length === 0) {
        return;
      }
      var output = document.createElement("span");
      output.className = "selection-count";
      output.setAttribute("aria-live", "polite");
      legend.appendChild(output);

      function update() {
        var selected = 0;
        Array.prototype.forEach.call(boxes, function (box) {
          if (box.checked) {
            selected += 1;
          }
        });
        /* textContent, never innerHTML: the only value written here is a
           number this file computed, and using textContent means that stays
           true even if somebody later writes something else into it. */
        output.textContent = selected > 0 ? " (" + selected + ")" : "";
      }

      Array.prototype.forEach.call(boxes, function (box) {
        box.addEventListener("change", update);
      });
      update();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      focusErrorSummary();
      announceSelectionCount();
    });
  } else {
    focusErrorSummary();
    announceSelectionCount();
  }
})();
