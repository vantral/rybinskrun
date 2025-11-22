document.addEventListener("DOMContentLoaded", function () {
    const toggles = document.querySelectorAll(".answer-mode-toggle");

    toggles.forEach(function (radio) {
        radio.addEventListener("change", function (event) {
            const qid = event.target.getAttribute("data-question-id");
            if (!qid) return;

            const textBlock = document.getElementById(`answer-text-block-${qid}`);
            const addressBlock = document.getElementById(`answer-address-block-${qid}`);

            if (event.target.value === "text") {
                if (textBlock) textBlock.classList.remove("d-none");
                if (addressBlock) addressBlock.classList.add("d-none");
            } else if (event.target.value === "address") {
                if (addressBlock) addressBlock.classList.remove("d-none");
                if (textBlock) textBlock.classList.add("d-none");
            }
        });
    });

    // ---- scroll to last answered question ----
    const meta = document.getElementById("last-question-meta");
    if (meta) {
        const qid = meta.getAttribute("data-last-question-id");
        if (qid) {
            const card = document.getElementById(`question-${qid}`);
            if (card) {
                card.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        }
    }
    const randomHintSpans = document.querySelectorAll(".hint-random");

    randomHintSpans.forEach(span => {
        const raw = span.getAttribute("data-hints");
        if (!raw) return;

        try {
            const list = JSON.parse(raw);
            if (Array.isArray(list) && list.length > 0) {
                const random = list[Math.floor(Math.random() * list.length)];
                span.textContent = random;
            }
        } catch (e) {
            console.error("Invalid hint list in data-hints:", e);
        }
    });
});
