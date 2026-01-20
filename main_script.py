import streamlit as st
import json
import pymupdf as fitz  # PyMuPDF
from openai import OpenAI
import time
import tempfile
import io
import hashlib
import os
import re

# -------------------------------
# INITIALIZATION
# -------------------------------
client = OpenAI()

st.set_page_config(
    page_title="📘 Residency and Fellowship Board Exam Short Answer Question Generator",
    page_icon="🧠",
    layout="centered"
)

st.title("📘 Residency and Fellowship Board Exam Short Answer Question Generator")
st.markdown("Upload a PDF, generate short-answer questions, answer the questions, and get feedback.")
st.markdown("If you are using a mobile device, make sure to use a pdf file that is downloaded locally, and not uploaded from a Cloud Drive to prevent an upload error.")

# -------------------------------
# SESSION STATE INITIALIZATION
# -------------------------------
if "question_set_id" not in st.session_state:
    st.session_state["question_set_id"] = 0

if "generate_new_set" not in st.session_state:
    st.session_state["generate_new_set"] = False

if "questions" not in st.session_state:
    st.session_state["questions"] = []

if "user_answers" not in st.session_state:
    st.session_state["user_answers"] = []

if "evaluations" not in st.session_state:
    st.session_state["evaluations"] = []

if "selected_prev_set" not in st.session_state:
    st.session_state["selected_prev_set"] = None

if "mode" not in st.session_state:
    st.session_state["mode"] = "idle"  # idle | generate | retry

if "current_set_id" not in st.session_state:
    st.session_state["current_set_id"] = None

if "generate_now" not in st.session_state:
    st.session_state["generate_now"] = False


# -------------------------------
# PDF UPLOAD
# -------------------------------
uploaded_file = st.file_uploader("📄 Upload a PDF file", type=["pdf"])

def extract_text_from_pdf(pdf_bytes):
    text = ""
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as pdf_doc:
        for page in pdf_doc:
            text += page.get_text("text")
    return text

if uploaded_file:
    if (
        "pdf_text" not in st.session_state
        or st.session_state.get("uploaded_file_name") != uploaded_file.name
    ):
        pdf_bytes = uploaded_file.getvalue()  # ✅ NOT .read()
        pdf_text = extract_text_from_pdf(pdf_bytes)

        st.session_state["pdf_text"] = pdf_text
        st.session_state["uploaded_file_name"] = uploaded_file.name

        st.success("✅ PDF uploaded successfully!")
    else:
        pdf_text = st.session_state["pdf_text"]

pdf_text = st.session_state.get("pdf_text", "")

if uploaded_file and not pdf_text:
    st.warning("PDF uploaded, but no text was extracted.")

# -------------------------------
# Question Topic Extraction
# -------------------------------
def extract_topics_from_questions(questions):
    """
    Extract short topic labels from a list of questions.
    """
    prompt = f"""
Extract a concise topic label (2–5 words) for each of the following oral board questions.
Return ONLY a JSON list of UNIQUE topic strings.

QUESTIONS:
{json.dumps([q["question"] for q in questions], indent=2)}
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```(?:json)?|```", "", raw).strip()
    return json.loads(raw)


def get_used_topics():
    """
    Aggregate all previously used topics from session state.
    """
    used = set()
    for s in st.session_state.get("all_question_sets", []):
        for t in s.get("topics", []):
            used.add(t)
    return sorted(list(used))

# -------------------------------
# QUESTION GENERATION (Single GPT Call, Previous Sets)
# -------------------------------
if uploaded_file:
    st.subheader("🧩 Step 1: Generate Short-Answer Questions")

    num_questions = st.slider("Number of questions to generate:",1, 10, key="num_questions")
    
    if not pdf_text:
        st.warning(
            "⚠️ This PDF appears to be scanned or image-based. "
            "Text extraction returned empty. OCR is required."
    )
    # Trigger generation if user clicks "Generate Questions" OR new set flag is set
    if st.button("⚡ Generate Questions"):
        if not pdf_text:
            st.error(
                "❌ Cannot generate questions because no text could be extracted.\n\n"
                "This PDF is likely scanned. Please upload a text-based PDF "
                "or enable OCR support."
            )
        else:
            st.session_state["generate_now"] = True
            st.session_state["question_set_id"] += 1
            st.rerun()
            
    if st.session_state.get("generate_now"):
        st.session_state["generate_now"] = False
    
        pdf_text = st.session_state["pdf_text"]
        progress = st.progress(0, text="Generating questions... please wait")


        # -------------------------------
        # 1️⃣ Prompt GPT to generate all questions
        # -------------------------------
        used_topics = get_used_topics()
        prompt = f"""
    You are an expert medical educator.
    Generate {num_questions} concise short-answer questions and their answer keys based on the following content.
    PREVIOUSLY USED TOPICS (avoid these unless no alternatives remain): {json.dumps(used_topics, indent=2)}
    Your target audience is residents and fellows.
    
    TASK:
    1. Identify ALL major topics in the source material.
    2. Exclude any topics listed above.
    3. Randomly select {num_questions} DIFFERENT remaining topics.
    4. Write ONE concise short-answer question per topic, structured like a Royal College of Physicians and Surgeons oral boards exam.
    
    RULES:
    - Ensure the questions are **proportional across the manual**, covering all major topics.
    - Each question must test a DIFFERENT topic
    - Do NOT generate multiple questions from the same subsection
    - Do NOT follow the order of the manual
    - Do NOT repeat themes from earlier question sets
    - Focus on clinical relevance
    - FOCUS on writing questions from tables, if tables are present
    - If surgical content exists, include presentation, approach, and management
    - Questions should resemble Royal College oral board style
    - Do NOT invent answer, answers should ONLY come from uploaded manual

    EXAMPLE QUESTION:
    A 30-years old male presents to the Emergency Room with a gunshot wound to the chest. There is a thru and thru gunshot wound to the right mainstem bronchus, what is the best treatment?

    EXAMPLE ANSWER:
    Right mainstem bronchus transection
    1. Secure the airway
    - Urgent intubation in trauma bay – single lumen ETT into left mainstem bronchus under direct vision with flexible bronchoscope
    2. Complete ABCs of trauma
    - Sub-dural hematomas, intra-abdominal bleeding, or major cardiovascular injuries should usually be repaired before definitive repair of the tracheobronchial injury
    3. Emergent operative repair
    - Let anesthesia know early that the goal will be extubation at the end of the case
    4. Operative approach (*Always remember to harvest an intercostal bundle at the time of thoracotomy)
    - Right mainstem is best accessed via right thoracotomy
    - Proximal tracheal injury: cervical collar incision
    - Distal trachea, right mainstem bronchus, carina, and proximal left mainstem bronchus: posterolateral right thoracotomy
    - Mid to distal left mainstem bronchus: left
    5. Simple, clean lacerations can repaired primarily using a simple interrupted absorbable suture (ie. 4-0 Vicryl or 3-0 PDS)
    - In a gunshot wound, the tissue will likely be devitalized, and the devitalized tissue should be debrided.
    o In these cases, a circumferential resection and end-to-end anastomosis is almost always preferable to partial wedge resections of traumatized airway with attempted primary repair.
    - Absorbable suture
    - Knots are on the outside of the airway
    6. At the time of surgery, for an airway injury, you should always additionally evaluate for esophageal injury by performing an EGD at the time of surgery (before closing, as you will need to repair the esophageal injury if identified).
    - Additionally, do bronch intra-op prior to thoracotomy and after repair.
    7. Wrap the repaired bronchus with either intercostal muscle, pericardial fat, or pleura.
    8. Plan to extubate the patient post-op.

    Additional notes:
    *You may additionally have vascular injuries, so you may need to do lung resection up to a pneumonectomy.
    - If C-spine is not cleared, you couldn’t do it via a lateral decubitus. Incision.
    - 4th intercostal space if you’re doing proximal or mid trachea vs 5th ICS to distal tracheal or carina
    - For transplant, they do 4th ICS
   
    *Something for the learners to reflect on:
    1) Criteria for primary repair versus circumferential resection and reanastomosis.
    - Primary repair for when you have clean edges, if you have to debride any tissue, then you should do a segmental resection.
    
    2) Tension release maneuvers.
    - Suprahyoid release (Montgomery)
    - Infrahyoid release (Thyrohyoid laryngeal release-Dedo)
    - Infra-hilar pericardial release
    - Release of the pre-tracheal fascia

    
    Return ONLY JSON in this format:
    [
      {{"topic": "string", "question": "string", "answer_key": "string"}}
    ]
    
    SOURCE TEXT:
    {pdf_text}
    """
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini-2025-04-14",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8
            )
            raw = response.choices[0].message.content.strip()
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            all_items = json.loads(raw)
    
            # Normalize structure
            all_questions = [
                {
                    "topic": item.get("topic", "").strip(),
                    "question": item.get("question", "").strip(),
                    "answer_key": item.get("answer_key", "").strip()
                }
                for item in all_items
                if item.get("question") and item.get("answer_key")
            ]
            
            progress.progress(50, text="Questions generated.")
    
        except Exception as e:
            st.error(f"⚠️ Question generation failed: {e}")
            all_questions = []
    
        if all_questions:
            unilingual_questions = all_questions

            # -------------------------------
            #  Save to session state
            # -------------------------------
            st.session_state["questions"] = unilingual_questions
            st.session_state["user_answers"] = [""] * len(unilingual_questions)
            progress.progress(100, text="✅ Done! Questions ready!")
    
            # -------------------------------
            #  Store previous sets
            # -------------------------------
            if "all_question_sets" not in st.session_state:
                st.session_state["all_question_sets"] = []
    
            topics = [q.get("topic", "") for q in all_questions if q.get("topic")]
            
            all_sets = st.session_state.get("all_question_sets", [])
            new_set_id = len(all_sets)  # unique incremental id
            
            st.session_state["all_question_sets"].append({
                "set_id": new_set_id,
                "questions": unilingual_questions,
                "topics": topics,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            })

            st.session_state["current_set_id"] = new_set_id
            st.success(f"Generated {len(unilingual_questions)} representative questions successfully!")

# -------------------------------
# USER ANSWERS (WITH AUDIO INPUT)
# -------------------------------
if st.session_state["questions"]:
    st.subheader("🧠 Step 2: Answer the Questions")

    questions = st.session_state["questions"]

    if "user_answers" not in st.session_state or len(st.session_state["user_answers"]) != len(questions):
        st.session_state["user_answers"] = [""] * len(questions)

    for i, q in enumerate(questions):
        st.markdown(f"### Q{i+1}. {q.get('question', '')}")

        st.markdown("🎤 Dictate your answer (you can record multiple times):")
        qid = st.session_state["question_set_id"]
        audio_data = st.audio_input(
            "",
            key=f"audio_input_{qid}_{i}"
        )

        transcriptions_key = f"transcriptions_{i}"
        last_hash_key = f"last_audio_hash_{i}"
        if transcriptions_key not in st.session_state:
            st.session_state[transcriptions_key] = []
        if last_hash_key not in st.session_state:
            st.session_state[last_hash_key] = None

        dictated_text = ""
        
        if audio_data is not None:
            try:
                audio_bytes = audio_data.getvalue()
                audio_hash = hashlib.sha256(audio_bytes).hexdigest()
        
                if st.session_state.get(last_hash_key) == audio_hash:
                    st.info("This recording was already transcribed.", icon="ℹ️")
                else:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                        tmp_file.write(audio_bytes)
                        tmp_path = tmp_file.name
        
                    with open(tmp_path, "rb") as f:
                        transcription = client.audio.transcriptions.create(
                            model="whisper-1",
                            file=f
                        )
        
                    os.remove(tmp_path)
        
                    dictated_text = getattr(transcription, "text", "").strip()
        
                    if dictated_text:
                        # ✅ Append to CURRENT text area value
                        existing_text = st.session_state.get(f"ans_{qid}_{i}", "").strip()
                        if existing_text:
                            new_text = f"{existing_text} {dictated_text}"
                        else:
                            new_text = dictated_text
        
                        st.session_state[f"ans_{qid}_{i}"] = new_text
                        st.session_state["user_answers"][i] = new_text
                        st.session_state[last_hash_key] = audio_hash
        
                        st.success("🎧 Dictation appended to your answer.", icon="🎤")
                    else:
                        st.warning("⚠️ Transcription returned empty text.")
        
            except Exception as e:
                st.error(f"⚠️ Audio transcription failed: {e}")

        label = "✏️ Your Answer:"
        key = f"ans_{qid}_{i}"  # unified key
        existing_text = st.session_state.get(key, "").strip()
        if existing_text:
            new_text = f"{existing_text} {dictated_text}"
        else:
            new_text = dictated_text
        
        st.session_state[key] = new_text
        st.session_state["user_answers"][i] = new_text
        
        current_text = st.text_area(label, height=80, key=key)

    user_answers = st.session_state.get("user_answers", [])

    # -------------------------------
    # EVALUATION
    # -------------------------------
    def score_short_answers(user_answers, questions):
        grading_prompt = f"""
        You are a supportive Royal College oral boards examiner assessing RESIDENT-LEVEL answers.
        
        Your goal is to fairly assess clinical understanding, not to fail candidates.
        
        IMPORTANT GRADING PHILOSOPHY:
        - Full marks (9–10/10) are achievable for clear, correct, resident-appropriate answers
        - Do NOT require consultant-level depth for full credit
        - Award generous partial credit for correct core concepts
        - Minor omissions or wording issues should NOT heavily penalize the score
        - Answers may be brief, non-native English, or in another language
        
        SCORING RUBRIC (0–10):
        - 9–10: Correct core concepts, clinically sound, safe management; minor details may be missing
        - 7–8: Mostly correct with good understanding; some gaps or imprecision
        - 5–6: Partial understanding; correct ideas but important omissions
        - 3–4: Limited understanding; some correct fragments
        - 1–2: Minimal understanding
        - 0: Unsafe or completely incorrect
        
        INSTRUCTIONS:
        1. Focus on whether the candidate demonstrates SAFE and CORRECT clinical reasoning
        2. Compare the response to the expected answer key, but do NOT require exact wording
        3. If the core idea is present, award at least 6/10
        4. Be especially fair to concise answers typical of oral exams
        
        Return ONLY JSON:
        [
          {{
            "score": 0,
            "feedback": "Brief, constructive feedback explaining the score.",
            "model_answer": "A concise ideal resident-level answer."
          }}
        ]
        
        QUESTIONS AND RESPONSES:
        {json.dumps([
            {
                "question": q.get("question", ""),
                "expected": q.get("answer_key", ""),
                "response": a
            }
            for q, a in zip(questions, user_answers)
        ], indent=2)}
        """
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": grading_prompt}],
                temperature=0
            )
            raw = response.choices[0].message.content.strip()
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            results = json.loads(raw)
    
            return results
        except Exception as e:
            st.error(f"⚠️ Scoring failed: {e}")
            return []

    if st.button("🚀 Evaluate My Answers"):
        with st.spinner("Evaluating your answers..."):
            results = score_short_answers(user_answers, questions)
            st.session_state['evaluations'] = results

        if results:
            # -------------------------------
            # Compute total score
            # -------------------------------
            total_score = sum(r.get("score", 0) for r in results)
            max_score = len(results) * 10  # each question max 10 points
            percentage = round(total_score / max_score * 100, 1)
    
            st.success("✅ Evaluation complete!")
    
            # -------------------------------
            # Display total score
            # -------------------------------
            st.markdown(f"### 🏆 {'Total Score'}: {total_score}/{max_score} ({percentage}%)")
            
            st.success("✅ Evaluation complete!")
            with st.expander("📊 Detailed Feedback"):
                for i, (q, r) in enumerate(zip(questions, results)):
                    st.markdown(f"### Q{i+1}: {q.get('question', '')}")
                    st.markdown(f"**Score:** {r.get('score', 'N/A')} / 10")
                    st.markdown(f"**Feedback (English):** {r.get('feedback', '')}")
                    st.markdown(f"**Model Answer (English):** {r.get('model_answer', '')}")
                    st.markdown("---")
                  
        if st.session_state.get("all_question_sets"):
            with st.expander("📚 Topics Covered So Far"):
                for used_topic_item in get_used_topics():
                    st.write(used_topic_item)

    # -------------------------------
    # NEW BUTTON: Generate a new set of questions
    # -------------------------------
    if st.button("🔄 Generate a New Set of Questions"):
        st.session_state["questions"] = []
        st.session_state["user_answers"] = []
        st.session_state["evaluations"] = []
        st.session_state["mode"] = "generate"
        st.session_state["generate_now"] = True
        st.session_state["question_set_id"] += 1
        st.rerun()
    
    url_feedback = "https://forms.gle/8cvfGhwNsd7fNAsd6"
    st.write("Thank you for trying this short answer question generator! Please click on the following links to provide feedback to help improve this tool:")
    st.markdown(url_feedback)
