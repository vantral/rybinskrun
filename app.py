import csv
import os
import json
from datetime import datetime

import requests
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ANSWERS_FILE = os.path.join(BASE_DIR, "answers", "answers.csv")
PROGRESS_FILE = os.path.join(BASE_DIR, "answers", "progress.json")

CATEGORY_DESCRIPTIONS = {
    "Игра в П": "Что-то в ответах на вопросы из этой категории начинается на букву П: либо часть названия, либо адрес.",
    "Иностранное агентство": "Ответы на вопросы из этой категории связаны с другими государствами.",
    "Money money money": "К названию этой категории добавить в общем-то и нечего",
    "Однажды четыре народа жили в мире…": "Каждый из ответов соответствует одной из базовых стихий (не исключаем, что соответствие притянуто за уши)"
}


# ---------------- Google Sheet config ---------------- #

SHEET_ID = "1U00vwP6gnM76qp3Mjgwhq70lmWtvjJI-Ci7c1d_JZgA"
# If the data is on the first tab, gid is usually 0. Change if needed.
SHEET_GID = "0"

SHEET_CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
    f"?format=csv&gid={SHEET_GID}"
)


# ------------- Normalisation helpers ------------- #

def norm_text(s: str) -> str:
    """Lowercase, collapse spaces, strip."""
    return " ".join((s or "").strip().lower().split())


def norm_number(s: str) -> str:
    """Normalise house numbers: lowercase and remove spaces."""
    return (s or "").strip().lower().replace(" ", "")


# ------------- Data loading from Google Sheets ------------- #

def load_questions():
    """
    Read questions from Google Sheet (CSV export), return:
    - questions_by_category: {category: [question_dict, ...]}
    - questions_by_id: {id: question_dict}

    Expected columns:
    id, category, question, hint, media,
    possible_answers, adress_yandex,
    street_status, street_name, n,
    answer, link
    """
    import io

    questions_by_category = {}
    questions_by_id = {}

    try:
        resp = requests.get(SHEET_CSV_URL, timeout=10)
        resp.raise_for_status()

        # IMPORTANT: force UTF-8 (strip BOM if present)
        csv_text = resp.content.decode("utf-8-sig")

    except Exception as e:
        print("ERROR loading Google Sheet:", e)
        return {}, {}

    reader = csv.DictReader(io.StringIO(csv_text))

    for row in reader:
        raw_id = (row.get("id") or "").strip()
        if not raw_id:
            continue

        try:
            q_id = int(raw_id)
        except ValueError:
            continue

        category = (row.get("category") or "Без категории").strip()
        question_text = (row.get("question") or "").strip()
        hint = (row.get("hint") or "").strip()
        media = (row.get("media") or "").strip()

        possible_raw = (row.get("possible_answers") or "").strip()
        possible_list = [x.strip() for x in possible_raw.split(";") if x.strip()]

        adress_yandex = (row.get("adress_yandex") or "").strip()
        street_status = (row.get("street_status") or "").strip()
        street_name = (row.get("street_name") or "").strip()
        house_n = (row.get("n") or "").strip()

        answer_text = (row.get("answer") or "").strip()
        answer_link = (row.get("link") or "").strip()

        q = {
            "id": q_id,
            "category": category,
            "question": question_text,
            "hint": hint,
            "media": media,

            "possible_answers": possible_list,
            "adress_yandex": adress_yandex,
            "street_status": street_status,
            "street_name": street_name,
            "house_n": house_n,
            "answer_text": answer_text,
            "answer_link": answer_link,
        }

        questions_by_id[q_id] = q
        questions_by_category.setdefault(category, []).append(q)

    for cat in questions_by_category:
        questions_by_category[cat].sort(key=lambda x: x["id"])

    return questions_by_category, questions_by_id

QUESTIONS_BY_CATEGORY, QUESTIONS_BY_ID = load_questions()


# ------------- Answer storage (log) ------------- #

def ensure_answers_file():
    os.makedirs(os.path.dirname(ANSWERS_FILE), exist_ok=True)
    if not os.path.exists(ANSWERS_FILE):
        with open(ANSWERS_FILE, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "player_code",
                "question_id",
                "answer_mode",
                "answer_text",
                "street_type",
                "street_name",
                "house_number",
            ])


def save_answer_log(
    question_id,
    player_code,
    answer_mode,
    answer_text="",
    street_type="",
    street_name="",
    house_number="",
):
    ensure_answers_file()
    timestamp = datetime.now().isoformat(timespec="seconds")
    with open(ANSWERS_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            timestamp,
            player_code or "",
            question_id,
            answer_mode,
            answer_text,
            street_type,
            street_name,
            house_number,
        ])


# ------------- Progress per player_code ------------- #

def load_progress():
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    if not os.path.exists(PROGRESS_FILE):
        return {}
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_progress(progress):
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def get_player_code():
    return session.get("player_code")


def set_player_code(code: str):
    session["player_code"] = code.strip()


def get_player_progress(player_code: str):
    if not player_code:
        return {}

    progress = load_progress()
    player_prog = progress.get(player_code, {})

    # Sync with current questions from Google Sheet
    player_prog, changed = sync_progress_with_questions(player_prog)

    if changed:
        progress[player_code] = player_prog
        save_progress(progress)

    return player_prog



def update_player_progress(player_code: str, question_id: int, data: dict):
    if not player_code:
        return
    all_progress = load_progress()
    player_prog = all_progress.get(player_code, {})
    player_prog[str(question_id)] = data
    all_progress[player_code] = player_prog
    save_progress(all_progress)


# ------------- Local checker based on Google Sheet data ------------- #

def check_answer_local(question, answer_mode, user_data):
    """
    `question` is the q dict from QUESTIONS_BY_ID.
    `answer_mode` is "text" or "address".
    `user_data` carries user input fields.

    Returns dict:
    {
        "correct": bool,
        "text": str,   # from CSV 'answer'
        "link": str,   # from CSV 'link'
    }
    """
    correct = False

    # --- TEXT MODE --- #
    if answer_mode == "text":
        user_text = norm_text(user_data.get("answer_text", ""))

        # 1) possible_answers list
        for cand in question.get("possible_answers", []):
            if user_text and user_text == norm_text(cand):
                correct = True
                break

        # 2) adress_yandex as additional possible variant
        if not correct:
            addr_yandex = question.get("adress_yandex") or ""
            if addr_yandex and user_text == norm_text(addr_yandex):
                correct = True

    # --- ADDRESS MODE --- #
    elif answer_mode == "address":
        user_status = norm_text(user_data.get("street_type", ""))
        user_street = norm_text(user_data.get("street_name", ""))
        user_n = norm_number(user_data.get("house_number", ""))

        q_status = norm_text(question.get("street_status", ""))
        q_street = norm_text(question.get("street_name", ""))
        q_n = norm_number(question.get("house_n", ""))

        if user_status == q_status and user_street == q_street and user_n == q_n:
            correct = True

    return {
        "correct": bool(correct),
        "text": question.get("answer_text") or "",
        "link": question.get("answer_link") or "",
    }


def sync_progress_with_questions(player_progress):
    """
    Ensure that for all solved questions, the stored text/link in progress
    match the current data from Google Sheets.
    """
    changed = False

    for qid_str, pdata in list(player_progress.items()):
        if not isinstance(pdata, dict):
            continue
        if not pdata.get("correct"):
            continue

        try:
            qid = int(qid_str)
        except ValueError:
            continue

        q = QUESTIONS_BY_ID.get(qid)
        if not q:
            continue

        new_text = q.get("answer_text") or ""
        new_link = q.get("answer_link") or ""

        old_text = pdata.get("text", "")
        old_link = pdata.get("link", "")

        if old_text != new_text or old_link != new_link:
            pdata["text"] = new_text
            pdata["link"] = new_link
            changed = True

    return player_progress, changed


# ------------- Routes ------------- #

@app.route("/", methods=["GET"])
def index():
    global QUESTIONS_BY_CATEGORY, QUESTIONS_BY_ID

    # Always get fresh data from Google Sheets
    QUESTIONS_BY_CATEGORY, QUESTIONS_BY_ID = load_questions()

    player_code = get_player_code()
    player_progress = get_player_progress(player_code)
    return render_template(
        "index.html",
        questions_by_category=QUESTIONS_BY_CATEGORY,
        player_code=player_code,
        player_progress=player_progress,
        category_descriptions=CATEGORY_DESCRIPTIONS,  # if you have this
    )




@app.route("/set_profile", methods=["POST"])
def set_profile():
    code = (request.form.get("player_code") or "").strip()
    if not code:
        flash("Придумай и введи код игрока (любое слово или фраза).", "warning")
        return redirect(url_for("index"))

    set_player_code(code)
    flash(f"Код игрока установлен: {code}", "success")
    return redirect(url_for("index"))


@app.route("/submit", methods=["POST"])
def submit_answer():
    question_id_raw = request.form.get("question_id")
    answer_mode = request.form.get("answer_mode")
    player_code = get_player_code()

    if not question_id_raw:
        flash("Ошибка: неизвестный вопрос.", "danger")
        return redirect(url_for("index"))

    try:
        question_id = int(question_id_raw)
    except ValueError:
        flash("Ошибка: неправильный идентификатор вопроса.", "danger")
        return redirect(url_for("index"))

    if question_id not in QUESTIONS_BY_ID:
        flash("Ошибка: такого вопроса нет.", "danger")
        return redirect(url_for("index"))

    if not player_code:
        flash("Сначала введи свой код игрока наверху страницы.", "warning")
        return redirect(url_for("index"))

    question = QUESTIONS_BY_ID[question_id]

    # --- collect and log user input --- #
    if answer_mode == "text":
        answer_text = (request.form.get("answer_text") or "").strip()
        if not answer_text:
            flash("Пожалуйста, введите ответ.", "warning")
            return redirect(url_for("index"))

        save_answer_log(
            question_id=question_id,
            player_code=player_code,
            answer_mode="text",
            answer_text=answer_text,
        )

        checker_input = {
            "answer_text": answer_text,
        }

    elif answer_mode == "address":
        street_type = (request.form.get("street_type") or "").strip()
        street_name = (request.form.get("street_name") or "").strip()
        house_number = (request.form.get("house_number") or "").strip()

        if not street_name or not house_number:
            flash("Заполни название улицы и номер дома.", "warning")
            return redirect(url_for("index"))

        save_answer_log(
            question_id=question_id,
            player_code=player_code,
            answer_mode="address",
            street_type=street_type,
            street_name=street_name,
            house_number=house_number,
        )

        checker_input = {
            "street_type": street_type,
            "street_name": street_name,
            "house_number": house_number,
        }
    else:
        flash("Ошибка: неизвестный тип ответа.", "danger")
        return redirect(url_for("index"))

    # --- local check using data from Google Sheet --- #
    result = check_answer_local(question, answer_mode, checker_input)

    if result["correct"]:
        flash("Верно! ✔️", "success")
        update_player_progress(
            player_code,
            question_id,
            {
                "correct": True,
                "text": result["text"],
                "link": result["link"],
            },
        )
    else:
        flash("Пока что неверно. Попробуй ещё раз.", "danger")

    return redirect(url_for("index"))


@app.route("/clear_progress", methods=["GET"])
def clear_progress():
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        pass
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
