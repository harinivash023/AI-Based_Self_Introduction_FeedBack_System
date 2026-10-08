from types import SimpleNamespace

import numpy as np
import pytest

from rubric_parser import RubricParser
from scoring_engine import ScoringEngine
from shared_scoring import CONTENT_SECTION_DEFINITIONS, SEMANTIC_THRESHOLDS
from shared_rubric import RubricParser as SharedRubricParser
from shared_scoring import ScoringEngine as SharedScoringEngine


@pytest.fixture
def scorer():
    engine = ScoringEngine(RubricParser().get_rubrics())
    engine.model_load_failed = True
    engine.language_tool_load_failed = True
    return engine


def criterion(result, name):
    return next(item for item in result["criteria_scores"] if item["criterion"] == name)


def test_strong_introduction_scores_content_sections(scorer):
    transcript = (
        "Good morning, everyone. My name is Bala, and I am a computer science graduate. "
        "I have technical skills in Python, SQL, machine learning, and FastAPI. "
        "I developed an image-classification application using Python to help researchers "
        "organize large collections of images. During my internship, I built a reporting "
        "dashboard with the engineering team. I earned a TensorFlow certification. "
        "I aspire to begin my career as a data scientist. Thank you for your time."
    )

    content = criterion(scorer.calculate_score(transcript), "Content & Structure")

    assert content["content_structure"]["score"] >= 30
    assert content["content_structure"]["max_score"] == 35
    assert content["content_structure"]["sections"]["experience"]["detected"]
    assert content["content_structure"]["sections"]["career_goal"]["detected"]
    assert content["weighted_score"] <= 40


def test_greeting_and_name_only_has_low_content_score(scorer):
    content = criterion(
        scorer.calculate_score("Hello. My name is Bala."),
        "Content & Structure",
    )

    assert content["content_structure"]["score"] < 15
    assert not content["content_structure"]["sections"]["education"]["detected"]


def test_basic_grammar_errors_return_corrections(scorer):
    language = criterion(
        scorer.calculate_score("I am study AI and I has good communication skill."),
        "Language & Grammar",
    )["language_grammar"]

    corrections = {
        (issue["original"], issue["suggestion"])
        for issue in language["issues"]
    }
    assert ("I am study", "I am studying") in corrections
    assert ("I has", "I have") in corrections
    assert language["score"] < 20


class SectionSemanticModel:
    def __init__(self, target_sentence, target_section):
        self.target_sentence = target_sentence
        self.target_section = target_section
        self.section_names = list(CONTENT_SECTION_DEFINITIONS)

    def encode(self, sentences, convert_to_numpy=True):
        vectors = np.zeros((len(sentences), len(self.section_names)))
        for row, sentence in enumerate(sentences):
            for section_index, (section_key, definition) in enumerate(
                CONTENT_SECTION_DEFINITIONS.items()
            ):
                if sentence in definition["references"]:
                    vectors[row, section_index] = 1.0
            if sentence == self.target_sentence:
                vectors[row, self.section_names.index(self.target_section)] = 1.0
        return vectors


def test_semantics_detect_education_without_education_keywords(scorer):
    required_example = (
        "I am currently pursuing my bachelor's degree in "
        "Artificial Intelligence and Data Science."
    )
    required_education = criterion(
        scorer.calculate_score(f"Hello. My name is Bala. {required_example}"),
        "Content & Structure",
    )["content_structure"]["sections"]["education"]
    assert required_education["detected"]

    candidate_sentence = "I am completing a course in artificial intelligence and data science."
    scorer.model = SectionSemanticModel(candidate_sentence, "education")
    transcript = f"Hello. My name is Bala. {candidate_sentence}"

    education = scorer.calculate_score(transcript)["criteria_scores"][0][
        "content_structure"
    ]["sections"]["education"]

    assert education["detected"]
    assert not education["rule_evidence"]
    assert education["semantic_similarity"] == 1.0


def test_semantic_thresholds_are_bounded_and_configured_per_section():
    assert set(SEMANTIC_THRESHOLDS) == set(CONTENT_SECTION_DEFINITIONS)
    assert all(0 < threshold < 1 for threshold in SEMANTIC_THRESHOLDS.values())


def test_career_intent_is_detected_but_general_interest_is_not(scorer):
    goal_result = scorer.calculate_score(
        "Hello. My name is Bala. I aspire to begin my career as a data scientist."
    )
    general_interest_result = scorer.calculate_score(
        "Hello. My name is Bala. I like data science."
    )

    assert criterion(goal_result, "Content & Structure")["content_structure"][
        "sections"
    ]["career_goal"]["detected"]
    assert not criterion(general_interest_result, "Content & Structure")[
        "content_structure"
    ]["sections"]["career_goal"]["detected"]


def test_fresher_is_not_penalized_for_omitting_work_experience(scorer):
    content = criterion(
        scorer.calculate_score(
            "Hello. My name is Bala. I am pursuing a bachelor's degree in computing."
        ),
        "Content & Structure",
    )["content_structure"]

    assert content["candidate_profile"] == "fresher_or_early_career"
    assert content["sections"]["experience"]["optional"]
    assert not content["sections"]["experience"]["applicable"]
    assert content["sections"]["experience"]["score"] == 0


def test_college_project_is_not_misclassified_as_work_experience(scorer):
    sections = criterion(
        scorer.calculate_score(
            "Hello. My name is Bala. I developed a college project using Python."
        ),
        "Content & Structure",
    )["content_structure"]["sections"]

    assert sections["projects"]["detected"]
    assert not sections["experience"]["detected"]


def test_repeated_words_and_phrases_are_reported(scorer):
    result = scorer.calculate_score(
        "AI is my interest. I really like AI because AI is interesting. "
        "AI is a field I like."
    )
    language = criterion(result, "Language & Grammar")["language_grammar"]
    repetition = next(
        item for item in criterion(result, "Language & Grammar")["metrics"]
        if item["metric"] == "Repetition"
    )

    assert "ai" in repetition["repeated_words"]
    assert any("ai" in phrase for phrase in repetition["repeated_phrases"])
    assert language["improvements"]


def test_technical_terms_are_not_reported_as_grammar_errors(scorer):
    transcript = "I use Python, SQL, machine learning, FastAPI, and TensorFlow."
    scorer.language_tool = SimpleNamespace(
        check=lambda text: [
            SimpleNamespace(
                offset=text.index(term),
                errorLength=len(term),
                replacements=["Other"],
                ruleId="MORFOLOGIK_RULE_EN_US",
                category="TYPOS",
                ruleIssueType="misspelling",
                message="Possible spelling issue.",
            )
            for term in ("Python", "SQL", "FastAPI", "TensorFlow")
        ]
    )

    language = criterion(
        scorer.calculate_score(transcript),
        "Language & Grammar",
    )["language_grammar"]

    assert language["issues"] == []
    assert language["score"] == 20


def test_web_compatibility_modules_use_shared_implementations():
    assert RubricParser is SharedRubricParser
    assert ScoringEngine is SharedScoringEngine


def test_language_category_keeps_twenty_point_weight_and_breakdown(scorer):
    language = criterion(
        scorer.calculate_score("Hello. My name is Bala. I study computer science."),
        "Language & Grammar",
    )

    assert language["weight"] == 20
    assert language["max_score"] == 20
    assert sum(metric["max_score"] for metric in language["metrics"]) == 20
