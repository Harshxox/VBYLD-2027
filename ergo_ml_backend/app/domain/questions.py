"""
All 40 ErgoCare questions. Single source of truth for the question bank.

OPTION ORDERING CONTRACT — please read before editing
------------------------------------------------------
Every question lists its options from HEALTHIEST to UNHEALTHIEST (ascending risk).
`option_risk()` scores a positional answer as `index / (n - 1) * 100`, so if you
add or reorder options you MUST keep the healthiest option first.

    ["Never", "Rarely", "Sometimes", "Often"]        -> risk 0, 33, 67, 100   OK
    ["Often", "Sometimes", "Rarely", "Never"]        -> risk 100, 67, 33, 0  WRONG

Questions whose options are NOT ordered that way carry an explicit `risk_map`
(keyed by the exact option text), which bypasses the positional rule entirely.
`scripts/verify_scoring.py` asserts this contract, so a mistake fails the tests
instead of silently inverting a participant's report.

Each entry includes id, text, options, category, and an optional risk_map for
non-linear answer scoring.
"""
from typing import Optional, Dict, List


CATEGORY_LABELS: Dict[str, str] = {
    "workload": "Workload stress",
    "eyes": "Eye strain",
    "posture": "Posture setup",
    "movement": "Movement habits",
    "recovery": "Recovery",
    "pain": "Body discomfort",
}

QUESTIONS: List[Dict] = [
    {
        "id": 1,
        "text": "How long do you usually work continuously before taking a short break?",
        "options": ["Less than 30 minutes", "1 hour", "1-2 hours", "More than 2 hours"],
        "category": "workload",
    },
    {
        "id": 2,
        "text": "At the end of a workday, how tired do your eyes usually feel?",
        "options": ["Not tired", "Slightly tired", "Moderately tired", "Very tired"],
        "category": "eyes",
    },
    {
        "id": 3,
        "text": "How many hours do you work on a laptop without an external keyboard or mouse?",
        "options": ["1-2", "3-4", "6-7", ">8"],
        "category": "posture",
    },
    {
        "id": 4,
        "text": "How often do long work sessions leave you feeling stiff?",
        "options": ["Never", "Once in a while", "Often", "Every Day"],
        "category": "pain",
    },
    {
        "id": 5,
        "text": "How often do you stretch during work hours?",
        "options": ["Multiple times a day", "Once a day", "A few times a week", "Never"],
        "category": "movement",
    },
    {
        "id": 6,
        "text": "Do you feel exhausted in a typical workday?",
        "options": ["Not exhausting", "Mildly exhausting", "Quite exhausting", "Extremely exhausting"],
        "category": "recovery",
    },
    {
        "id": 7,
        "text": "How often do work deadlines affect your posture or comfort?",
        "options": ["Never", "Sometimes", "Often", "Always"],
        "category": "workload",
    },
    {
        "id": 8,
        "text": "How supportive is your chair for long hours of work?",
        "options": ["Very supportive", "Somewhat supportive", "Slightly supportive", "Not supportive at all"],
        "category": "posture",
    },
    {
        "id": 9,
        "text": "Where is your screen usually placed while working?",
        "options": ["At eye level", "Slightly below eye level", "Far below eye level", "I frequently change sometimes"],
        "category": "posture",
    },
    {
        "id": 10,
        "text": "How often do you use your phone during or between work sessions?",
        "options": ["Rarely", "1-2 times a day", "3-5 times a day", "Very frequently"],
        "category": "eyes",
    },
    {
        "id": 11,
        "text": "How much physical discomfort do you feel by the end of the week?",
        "options": ["None", "Mild", "Moderate", "Severe"],
        "category": "pain",
    },
    {
        "id": 12,
        "text": "How often do you feel wrist or finger strain while typing?",
        "options": ["Never", "Rarely", "Often", "Very often"],
        "category": "pain",
    },
    {
        "id": 13,
        "text": "How often do you work in poor lighting conditions?",
        "options": ["Never", "Occasionally", "Frequently", "Always"],
        "category": "eyes",
    },
    {
        "id": 14,
        "text": "How often do you feel your shoulders become tense while working?",
        "options": ["Never", "Sometimes", "Often", "Everyday"],
        "category": "pain",
    },
    {
        "id": 15,
        "text": "How frequently do you switch between sitting and standing while working?",
        "options": ["Very frequently", "Sometimes", "Rarely", "Never"],
        "category": "movement",
    },
    {
        "id": 16,
        "text": "How often do you continue working even when you feel discomfort?",
        "options": ["Never", "Sometimes", "Often", "Always"],
        "category": "workload",
    },
    {
        "id": 17,
        "text": "How well does your body recover after a long day of work?",
        # Reads naturally worst-first, so the positional rule would score "Not at
        # all" as 0 risk. risk_map states the intent explicitly.
        "options": ["Not at all", "Slightly", "Mostly", "Completely"],
        "risk_map": {"Not at all": 100, "Slightly": 67, "Mostly": 33, "Completely": 0},
        "category": "recovery",
    },
    {
        "id": 18,
        "text": "How often do you notice headaches after screen-heavy work?",
        "options": ["Never", "Sometimes", "Often", "Always"],
        "category": "eyes",
    },
    {
        "id": 19,
        "text": "How often do you adjust your sitting position during work?",
        # Frequent micro-adjustment prevents posture fixation, so "Often" is the
        # healthy end - the reverse of the option order.
        "options": ["Never", "Rarely", "Sometimes", "Often"],
        "risk_map": {"Never": 100, "Rarely": 67, "Sometimes": 33, "Often": 0},
        "category": "posture",
    },
    {
        "id": 20,
        "text": "How often do you push through physical discomfort just to keep working?",
        "options": ["Never", "Sometimes", "Often", "Always"],
        "category": "workload",
    },
    {
        "id": 21,
        "text": "How many hours per day do you spend in front of a screen across all devices combined?",
        "options": ["Less than 4 hours", "4-6 hours", "6-8 hours", "More than 8 hours"],
        "category": "eyes",
    },
    {
        "id": 22,
        "text": "Do you feel your workload leaves you sufficient time for personal well-being activities?",
        "options": ["Yes, comfortably", "Often", "Rarely", "Never"],
        "category": "workload",
    },
    {
        "id": 23,
        "text": "How confident are you that your current work habits will support your long-term physical and mental health?",
        "options": ["Very confident", "Somewhat confident", "Uncertain", "Not confident at all"],
        "category": "recovery",
    },
    {
        "id": 24,
        "text": "How often do you consciously correct your posture while working?",
        # Correcting only once pain appears is already too late, so "Frequently
        # throughout the day" is the healthy end.
        "options": ["Never think about it", "Only when I feel pain", "Occasionally", "Frequently throughout the day"],
        "risk_map": {"Never think about it": 100, "Only when I feel pain": 67, "Occasionally": 33, "Frequently throughout the day": 0},
        "category": "posture",
    },
    {
        "id": 25,
        "text": "How often do you skip meals or eat at your desk due to workload?",
        "options": ["Never", "1-2 times a week", "3-4 times a week", "Often"],
        "category": "workload",
    },
    {
        "id": 26,
        "text": "Which best describes your physical activity pattern on a typical workday?",
        "options": [
            "Light movement such as walking between buildings",
            "Structured activity like yoga or a gym session",
            "Mostly seated with minimal movement",
            "Vigorous daily exercise routine",
        ],
        "category": "movement",
        "risk_map": {
            "light movement such as walking between buildings": 35,
            "structured activity like yoga or a gym session": 10,
            "mostly seated with minimal movement": 100,
            "vigorous daily exercise routine": 5,
        },
    },
    {
        "id": 27,
        "text": "How much water do you typically consume throughout your working hours?",
        # More water is healthier, so the healthiest option is last.
        "options": ["Less than 1 litre", "1-2 litres", "More than 2 litres"],
        "risk_map": {"Less than 1 litre": 100, "1-2 litres": 50, "More than 2 litres": 0},
        "category": "recovery",
    },
    {
        "id": 28,
        "text": "How much time do you spend commuting to and from work each day in total?",
        "options": ["Under 30 minutes", "30-60 minutes", "1-2 hours", "Over 2 hours"],
        "category": "recovery",
    },
    {
        "id": 29,
        "text": "How physically draining do you find your daily commute?",
        "options": ["Not draining at all", "Mildly tiring", "Moderately exhausting", "Severely fatiguing, it impacts my workday"],
        "category": "recovery",
    },
    {
        "id": 30,
        "text": "How often do you experience difficulty falling or staying asleep due to work-related thoughts?",
        "options": ["Never", "Rarely", "Sometimes", "Often"],
        "category": "recovery",
    },
    {
        "id": 31,
        "text": "How would you rate any stiffness or aching in your neck after long screen sessions?",
        "options": ["0", "1", "2", "3", "4", "5"],
        "category": "pain",
    },
    {
        "id": 32,
        "text": "How often does turning your head side to side feel restricted or painful?",
        # "Never" is healthy, so the option list runs worst-first.
        "options": ["Always", "Often", "Sometimes", "Rarely", "Never"],
        "risk_map": {"Always": 100, "Often": 75, "Sometimes": 50, "Rarely": 25, "Never": 0},
        "category": "pain",
    },
    {
        "id": 33,
        "text": "How would you rate the heaviness or burning sensation across your upper back or shoulder blades?",
        "options": ["0", "1", "2", "3", "4", "5"],
        "category": "pain",
    },
    {
        "id": 34,
        "text": "Do you experience pain or tightness when lifting your arms above shoulder height?",
        "options": ["Yes", "No", "Maybe"],
        "category": "pain",
    },
    {
        "id": 35,
        "text": "Rate the lower back pain you experience after sitting continuously for more than an hour.",
        "options": ["0", "1", "2", "3", "4", "5"],
        "category": "pain",
    },
    {
        "id": 36,
        "text": "Do you experience radiating pain or numbness from your lower back down into your legs at the end of the day?",
        "options": ["Yes", "No", "Maybe"],
        "category": "pain",
    },
    {
        "id": 37,
        "text": "How would you rate any aching or stiffness in your wrist when gripping a pen or mouse?",
        "options": ["0", "1", "2", "3", "4", "5"],
        "category": "pain",
    },
    {
        "id": 38,
        "text": "Do you experience a dull ache along your forearm or elbow after extended writing or clicking?",
        "options": ["Yes", "No", "Maybe"],
        "category": "pain",
    },
    {
        "id": 39,
        "text": "How would you rate the dryness, burning, or blurring of vision after extended screen time?",
        "options": ["0", "1", "2", "3", "4", "5"],
        "category": "eyes",
    },
    {
        "id": 40,
        "text": "Do you experience a general sense of physical exhaustion or body ache by the end of your workday that is not linked to any single region?",
        "options": ["Yes", "No", "Maybe"],
        "category": "recovery",
    },
]

QUESTIONS_BY_ID: Dict[int, Dict] = {q["id"]: q for q in QUESTIONS}
