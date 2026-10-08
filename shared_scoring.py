"""Shared rubric-driven scoring for the web and video pipelines."""
from collections import Counter
import logging
import math
import os
import re
import string
import threading

os.environ.setdefault("USE_TF", "0")

LOGGER = logging.getLogger(__name__)

CONTENT_SECTION_DEFINITIONS = {
    "greeting": {
        "name": "Greeting", "max_score": 4, "importance": "required",
        "references": [
            "Hello everyone, thank you for giving me the opportunity to introduce myself.",
            "Good morning, I am pleased to meet you.",
        ],
        "patterns": [r"\b(?:hello|hi|good morning|good afternoon|good evening|greetings)\b"],
    },
    "name": {
        "name": "Name / Personal Introduction", "max_score": 5, "importance": "required",
        "references": [
            "My name is Bala, and I am an artificial intelligence student.",
            "I am Bala, a computer science graduate.",
        ],
        "patterns": [
            r"\b(?:my name is|i am called|i'm called|call me|known as)\b",
            r"\b(?:i am|i'm)\s+[A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})?(?=[\s,.;])",
        ],
    },
    "education": {
        "name": "Education", "max_score": 6, "importance": "required",
        "references": [
            "I am currently pursuing my bachelor's degree in Artificial Intelligence and Data Science.",
            "I completed a computer science degree at university.",
            "I am in my final year of a bachelor's program in computer science.",
        ],
        "patterns": [
            r"\b(?:pursu(?:e|ing|ed)|bachelor'?s?|master'?s?|degree|diploma|graduate(?:d)?|"
            r"stud(?:y|ying)|college|university|school|enrolled|academic|final year|"
            r"computer science student|engineering student)\b",
        ],
    },
    "skills": {
        "name": "Technical Skills", "max_score": 5, "importance": "recommended",
        "references": [
            "My technical skills include Python, SQL, and machine learning.",
            "I have experience with software development and cloud platforms.",
        ],
        "patterns": [
            r"\b(?:skills?|proficient|familiar|knowledge|experienced|expertise|"
            r"technical background|programming languages?|technology stack)\b",
            r"\b(?:python|sql|java|javascript|c\+\+|machine learning|data analysis|"
            r"tensorflow|fastapi|react|aws|azure|docker)\b",
        ],
    },
    "projects": {
        "name": "Projects", "max_score": 4, "importance": "recommended",
        "references": [
            "I built a machine learning application to classify images.",
            "My final-year project was a web application for tracking expenses.",
        ],
        "patterns": [
            r"\b(?:project|capstone|prototype|application|app|website|platform|"
            r"developed|built|implemented|designed|created)\b",
        ],
    },
    "experience": {
        "name": "Internship / Work Experience", "max_score": 3, "importance": "optional",
        "references": [
            "During my internship, I worked on a machine learning project.",
            "I worked as a software engineer at a company for three years.",
            "My professional experience includes working as a data analyst.",
        ],
        "patterns": [
            r"\b(?:internship|intern|work experience|professional experience|"
            r"employed|currently work(?:ing)?|worked as|working as|years? of experience|"
            r"full[- ]time|part[- ]time|job role)\b",
        ],
    },
    "achievements": {
        "name": "Achievements / Certifications", "max_score": 2, "importance": "optional",
        "references": [
            "I earned a certification in cloud computing.",
            "I received first place in a national programming competition.",
        ],
        "patterns": [
            r"\b(?:achievement|award|certification|certified|won|winner|"
            r"recognized|recognition|ranked|first place|scholarship|hackathon)\b",
        ],
    },
    "career_goal": {
        "name": "Career Goal / Role Interest", "max_score": 3, "importance": "recommended",
        "references": [
            "I aspire to begin my career as a data scientist.",
            "My goal is to become a software engineer.",
            "I am interested in pursuing a career in cybersecurity.",
        ],
        "patterns": [
            r"\b(?:aspire|hope|aim|plan|intend|want|would like|wish|goal|objective|"
            r"interested in becoming|interested in pursuing|career in|career as)\b",
        ],
    },
    "closing": {
        "name": "Closing", "max_score": 3, "importance": "recommended",
        "references": [
            "Thank you for listening to my introduction.",
            "I look forward to discussing my experience with you.",
        ],
        "patterns": [
            r"\b(?:thank you|thanks for|i appreciate your time|look forward to|"
                r"pleasure speaking|that is all about me|appreciate your time)\b",
        ],
    },
}

SEMANTIC_THRESHOLDS = {
    "greeting": 0.48,
    "name": 0.52,
    "education": 0.58,
    "skills": 0.68,
    "projects": 0.55,
    "experience": 0.68,
    "achievements": 0.80,
    "career_goal": 0.61,
    "closing": 0.40,
}

LANGUAGE_METRIC_WEIGHTS = {
    "grammar": 8,
    "sentence_structure": 3,
    "vocabulary": 3,
    "repetition": 2,
    "completeness": 2,
    "mechanics": 2,
}

TECHNICAL_TERMS = {
    "ai", "aws", "azure", "c++", "css", "docker", "fastapi", "html",
    "javascript", "machine learning", "numpy", "pandas", "python", "react",
    "scikit-learn", "sql", "tensorflow", "torch", "pytorch", "flask",
}

GRAMMAR_RULES = (
    (
        re.compile(r"\bI am\s+(study|pursue|work|learn|develop|build)\b", re.IGNORECASE),
        {"study": ("I am studying", "Use the -ing form after 'I am'."),
         "pursue": ("I am pursuing", "Use the -ing form after 'I am'."),
         "work": ("I am working", "Use the -ing form after 'I am'."),
         "learn": ("I am learning", "Use the -ing form after 'I am'."),
         "develop": ("I am developing", "Use the -ing form after 'I am'."),
         "build": ("I am building", "Use the -ing form after 'I am'.")},
        "verb_form",
        "medium",
    ),
    (
        re.compile(r"\bI\s+(has|is|does)\b", re.IGNORECASE),
        {"has": ("I have", "Use the base verb form with 'I'."),
         "is": ("I am", "Use 'am' with the first-person subject 'I'."),
         "does": ("I do", "Use 'do' with the first-person subject 'I'.")},
        "subject_verb_agreement",
        "medium",
    ),
    (
        re.compile(r"\b(he|she|it|this|that)\s+(have|are|do)\b", re.IGNORECASE),
        {"have": (None, "Use a singular verb with this subject."),
         "are": (None, "Use a singular verb with this subject."),
         "do": (None, "Use a singular verb with this subject.")},
        "subject_verb_agreement",
        "medium",
    ),
)

_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)?|[A-Z][A-Za-z0-9+#.-]*")
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)|[^\n]+")
_INTENTION_RE = re.compile(
    r"\b(?:aspire|hope|aim|plan|intend|want|would like|wish|goal|objective|"
    r"interested in becoming|interested in pursuing|career in|career as)\b",
    re.IGNORECASE,
)
_ROLE_RE = re.compile(
    r"\b(?:career|role|profession|job|as an?\s+\w+|data scientist|"
    r"software engineer|data analyst|developer|designer|researcher|"
    r"project manager|cybersecurity|machine learning engineer)\b",
    re.IGNORECASE,
)
_EXPERIENCE_CLAIM_RE = re.compile(
    r"\b(?:years? of experience|worked as|working as|employed|"
    r"currently work(?:ing)?|professional experience|full[- ]time role)\b",
    re.IGNORECASE,
)


class ScoringEngine:
    def __init__(self, rubrics):
        self.rubrics = rubrics
        self.model = None
        self.model_load_failed = False
        self._model_lock = threading.Lock()
        self.greeting_patterns = [
            "Hello everyone, I am happy to introduce myself",
            "Good morning, I am excited to be here",
            "Hi, my name is"
        ]
        self._greeting_embeddings = None
        self._section_reference_embeddings = None
        self.language_tool = None
        self.language_tool_load_failed = False
        self._language_tool_lock = threading.Lock()

    @staticmethod
    def normalize_duration(duration_seconds):
        """Validate and normalize duration input used for WPM calculations."""
        if duration_seconds is None:
            return None

        if isinstance(duration_seconds, str):
            duration_seconds = duration_seconds.strip()
            if not duration_seconds:
                return None

        try:
            duration_seconds = float(duration_seconds)
        except (TypeError, ValueError):
            raise ValueError("duration_seconds must be a positive number.")

        if not math.isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("duration_seconds must be a positive number.")

        return duration_seconds

    def get_model(self):
        """Load the semantic model only when a metric needs it."""
        if self.model or self.model_load_failed:
            return self.model

        with self._model_lock:
            if self.model or self.model_load_failed:
                return self.model
            try:
                LOGGER.info("Loading sentence-transformer model all-MiniLM-L6-v2.")
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer("all-MiniLM-L6-v2")
            except Exception as exc:
                self.model_load_failed = True
                LOGGER.warning(
                    "Semantic matching unavailable; rule-based section detection remains active: %s",
                    exc,
                )
        return self.model
    
    def calculate_score(self, transcript, duration_seconds=None):
        """
        Main scoring function
        Returns: dict with overall score and per-criterion scores
        """
        normalized_duration = self.normalize_duration(duration_seconds)
        words = transcript.split()
        word_count = len(words)

        # Calculate WPM if duration provided
        wpm = None
        if normalized_duration is not None:
            wpm = (word_count / normalized_duration) * 60

        results = {
            "overall_score": 0,
            "word_count": word_count,
            "criteria_scores": [],
            "metadata": {
                "wpm": wpm,
                "duration_seconds": normalized_duration
            }
        }
        
        total_weighted_score = 0
        total_weight = 0
        
        # Process each criterion
        for criterion in self.rubrics["criteria"]:
            criterion_result = self.score_criterion(transcript, criterion, wpm, word_count)
            results["criteria_scores"].append(criterion_result)
            
            total_weighted_score += criterion_result["weighted_score"]
            total_weight += criterion["weight"]
        
        # Calculate overall score (0-100)
        results["overall_score"] = round(total_weighted_score, 2)
        
        return results
    
    def score_criterion(self, transcript, criterion, wpm, word_count):
        """Score a single criterion"""
        criterion_name = criterion["name"]
        normalized_name = criterion_name.lower().replace("&", "and")
        if normalized_name == "content and structure":
            return self.score_content_structure(transcript, criterion)
        if normalized_name == "language and grammar":
            return self.score_language_and_grammar(transcript, criterion)

        metrics_scores = []
        total_metric_score = 0
        max_possible_score = 0
        
        for metric in criterion["metrics"]:
            metric_score = self.score_metric(transcript, metric, criterion_name, wpm, word_count)
            metrics_scores.append(metric_score)
            total_metric_score += metric_score["score"]
            max_possible_score += metric["max_score"]
        
        # Calculate normalized score for this criterion
        if max_possible_score > 0:
            normalized_score = (total_metric_score / max_possible_score) * criterion["weight"]
        else:
            normalized_score = 0
        
        return {
            "criterion": criterion_name,
            "weight": criterion["weight"],
            "score": round(total_metric_score, 2),
            "max_score": max_possible_score,
            "weighted_score": round(normalized_score, 2),
            "metrics": metrics_scores
        }

    @staticmethod
    def _sentences(transcript):
        return [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", transcript)
            if sentence.strip()
        ]

    def _semantic_section_scores(self, sentences):
        """Return per-section best similarities, loading the model only when needed."""
        if not sentences:
            return {}
        model = self.get_model()
        if model is None:
            return {}

        section_names = list(CONTENT_SECTION_DEFINITIONS)
        reference_sentences = [
            sentence
            for section in section_names
            for sentence in CONTENT_SECTION_DEFINITIONS[section]["references"]
        ]
        if self._section_reference_embeddings is None:
            self._section_reference_embeddings = model.encode(
                reference_sentences, convert_to_numpy=True
            )
        sentence_embeddings = model.encode(sentences, convert_to_numpy=True)
        from sklearn.metrics.pairwise import cosine_similarity

        similarities = cosine_similarity(
            sentence_embeddings, self._section_reference_embeddings
        )
        scores = {}
        reference_offset = 0
        for section_key in section_names:
            reference_count = len(CONTENT_SECTION_DEFINITIONS[section_key]["references"])
            section_scores = similarities[
                :, reference_offset:reference_offset + reference_count
            ]
            scores[section_key] = [float(row.max()) for row in section_scores]
            reference_offset += reference_count
        return scores

    @staticmethod
    def _rule_evidence(section_key, sentences):
        patterns = CONTENT_SECTION_DEFINITIONS[section_key]["patterns"]
        found = []
        for sentence in sentences:
            if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in patterns):
                found.append(sentence)
        return found

    @staticmethod
    def _section_context_is_valid(section_key, sentence, sentences, sentence_index):
        lowered = sentence.lower()
        if section_key == "skills":
            technology = re.search(
                r"\b(?:python|sql|java|javascript|c\+\+|machine learning|data analysis|"
                r"tensorflow|fastapi|react|aws|azure|docker|programming|software|cloud)\b",
                lowered,
            )
            skill_context = re.search(
                r"\b(?:skill|proficient|familiar|knowledge|experience|expertise|"
                r"background|using|with|include|includes)\b",
                lowered,
            )
            return bool(technology and skill_context)
        if section_key == "projects":
            return bool(re.search(
                r"\b(?:project|capstone|prototype|application|app|website|platform|"
                r"system|model|built|developed|implemented|designed|created)\b",
                lowered,
            ))
        if section_key == "education":
            return bool(re.search(
                r"\b(?:semester|undergraduate|postgraduate|student|academic|course|coursework|"
                r"university|college|school|degree|graduate|studying|pursuing|"
                r"enrolled|program|programme|year)\b",
                lowered,
            ))
        if section_key == "name":
            return bool(re.search(
                r"\b(?:my name is|i am called|i'm called|call me|known as|"
                r"introduce myself as)\b",
                lowered,
            ))
        if section_key == "experience":
            if re.search(r"\b(?:college|university|class|course)\s+project\b", lowered):
                return bool(re.search(r"\b(?:internship|intern|worked as|work experience)\b", lowered))
            return bool(re.search(
                r"\b(?:internship|intern|job|employer|company|worked as|working as|"
                r"employed|professional|years? of experience|full[- ]time)\b",
                lowered,
            ))
        if section_key == "career_goal":
            return bool(_INTENTION_RE.search(sentence) and _ROLE_RE.search(sentence))
        if section_key == "achievements":
            return bool(re.search(
                r"\b(?:award|certif|won|winner|recognized|recognition|rank|"
                r"scholarship|hackathon|achievement)\b",
                lowered,
            ))
        if section_key == "greeting":
            return sentence_index < 2
        if section_key == "closing":
            return sentence_index >= max(0, len(sentences) - 2)
        return True

    @staticmethod
    def _section_quality(section_key, evidence):
        text = " ".join(evidence).lower()
        detail_signals = {
            "greeting": [
                bool(re.search(r"\b(?:opportunity|pleasure|meet|interview|everyone)\b", text)),
            ],
            "name": [
                bool(re.search(r"\b(?:student|graduate|engineer|developer|analyst|professional)\b", text)),
            ],
            "education": [
                bool(re.search(r"\b(?:bachelor|master|degree|diploma|b\.?tech|m\.?tech)\b", text)),
                bool(re.search(r"\b(?:artificial intelligence|data science|computer science|engineering|college|university)\b", text)),
            ],
            "skills": [
                bool(re.search(r"\b(?:python|sql|java|javascript|c\+\+|machine learning|data analysis|tensorflow|fastapi|react|aws|azure|docker)\b", text)),
                bool(re.search(r"\b(?:proficient|experience|expertise|develop|build|use|using)\b", text)),
            ],
            "projects": [
                bool(re.search(r"\b(?:built|developed|implemented|designed|created)\b", text)),
                bool(re.search(r"\b(?:using|with|to|for|that)\b", text)),
                bool(re.search(r"\b(?:result|improv|help|enable|reduce|automate|classif|track)\w*\b", text)),
            ],
            "experience": [
                bool(re.search(r"\b(?:internship|intern|worked as|working as|employed|professional experience)\b", text)),
                bool(re.search(r"\b(?:company|team|organization|months?|years?|responsibilit|contribut)\w*\b", text)),
            ],
            "achievements": [
                bool(re.search(r"\b(?:certif|award|won|winner|rank|recognized|scholarship|hackathon)\w*\b", text)),
            ],
            "career_goal": [
                bool(_INTENTION_RE.search(text)),
                bool(re.search(r"\b(?:data scientist|software engineer|developer|analyst|designer|researcher|manager|career|role|profession)\b", text)),
            ],
            "closing": [
                bool(re.search(r"\b(?:thank you|appreciate|look forward|pleasure)\b", text)),
            ],
        }[section_key]
        if not evidence:
            return 0.0
        return 0.55 + 0.45 * sum(detail_signals) / max(len(detail_signals), 1)

    @staticmethod
    def _candidate_profile(transcript):
        return "experienced" if _EXPERIENCE_CLAIM_RE.search(transcript) else "fresher_or_early_career"

    def score_content_structure(self, transcript, criterion):
        sentences = self._sentences(transcript)
        rule_evidence = {
            key: self._rule_evidence(key, sentences)
            for key in CONTENT_SECTION_DEFINITIONS
        }
        unresolved = [
            key for key, evidence in rule_evidence.items()
            if not evidence and CONTENT_SECTION_DEFINITIONS[key]["importance"] != "optional"
        ]
        semantic_scores = self._semantic_section_scores(sentences) if unresolved else {}
        sections = {}
        raw_score = 0.0
        eligible_max = 0

        for key, definition in CONTENT_SECTION_DEFINITIONS.items():
            evidence = rule_evidence[key]
            sentence_scores = semantic_scores.get(key, [])
            contextual_matches = [
                sentence for index, sentence in enumerate(sentences)
                if index < len(sentence_scores)
                and sentence_scores[index] >= SEMANTIC_THRESHOLDS[key]
                and self._section_context_is_valid(key, sentence, sentences, index)
            ]
            semantic_score = max(sentence_scores, default=0.0)
            detected = bool(evidence)
            if not detected and contextual_matches:
                evidence = contextual_matches
                detected = True

            experienced_claim = (
                key == "experience"
                and self._candidate_profile(transcript) == "experienced"
            )
            applicable = (
                definition["importance"] != "optional"
                or detected
                or experienced_claim
            )
            if applicable:
                eligible_max += definition["max_score"]

            section_quality = self._section_quality(key, evidence)
            section_score = round(definition["max_score"] * section_quality) if detected else 0
            raw_score += section_score
            sections[key] = {
                "name": definition["name"],
                "detected": detected,
                "score": section_score,
                "max_score": definition["max_score"],
                "importance": definition["importance"],
                "optional": definition["importance"] == "optional",
                "applicable": applicable,
                "rule_evidence": bool(rule_evidence[key]),
                "semantic_similarity": round(semantic_score, 3) if semantic_scores else None,
                "evidence": evidence[:3],
                "feedback": (
                    f"{definition['name']} detected with relevant detail."
                    if detected and section_quality >= 0.85
                    else f"{definition['name']} detected; add specific supporting details."
                    if detected
                    else f"{definition['name']} is not clearly presented."
                ),
            }

        max_score = sum(section["max_score"] for section in CONTENT_SECTION_DEFINITIONS.values())
        eligible_max = max(eligible_max, 1)
        normalized_content_score = round(raw_score / eligible_max * max_score, 2)
        structure = self._assess_structure(sentences, sections)
        if structure["penalty"]:
            normalized_content_score = max(0, normalized_content_score - structure["penalty"])

        strengths = [
            section["feedback"]
            for section in sections.values()
            if section["detected"] and section["score"] >= section["max_score"] * 0.75
        ]
        improvements = [
            section["feedback"]
            for section in sections.values()
            if not section["detected"] and section["importance"] != "optional"
        ]
        improvements.extend(structure["feedback"])
        profile = self._candidate_profile(transcript)
        if profile == "experienced" and not sections["experience"]["detected"]:
            improvements.append("Add a concise description of your relevant work experience.")
        summary = (
            f"Detected {sum(item['detected'] for item in sections.values())} of "
            f"{sum(item['applicable'] for item in sections.values())} applicable introduction sections."
        )
        section_metrics = []
        for key, section in sections.items():
            section_metrics.append({
                "metric": section["name"],
                "score": section["score"],
                "max_score": section["max_score"],
                "detected": section["detected"],
                "importance": section["importance"],
                "feedback": section["feedback"],
                "evidence": section["evidence"],
            })

        category_weight = criterion["weight"]
        weighted_score = round(normalized_content_score / max_score * category_weight, 2)
        return {
            "criterion": criterion["name"],
            "weight": category_weight,
            "score": round(normalized_content_score, 2),
            "max_score": max_score,
            "weighted_score": weighted_score,
            "metrics": section_metrics,
            "content_structure": {
                "score": round(normalized_content_score, 2),
                "max_score": max_score,
                "earned_section_points": round(raw_score, 2),
                "applicable_section_points": eligible_max,
                "candidate_profile": profile,
                "sections": sections,
                "structure": structure,
                "feedback": {
                    "summary": summary,
                    "strengths": strengths,
                    "improvements": improvements,
                },
            },
        }

    @staticmethod
    def _assess_structure(sentences, sections):
        order = [
            "greeting", "name", "education", "skills", "experience",
            "projects", "achievements", "career_goal", "closing",
        ]
        positions = {}
        for section_key in order:
            section = sections[section_key]
            if section["detected"]:
                for index, sentence in enumerate(sentences):
                    if sentence in section["evidence"]:
                        positions[section_key] = index
                        break

        present = [key for key in order if key in positions]
        inversions = sum(
            positions[left] > positions[right]
            for index, left in enumerate(present)
            for right in present[index + 1:]
        )
        penalty = 2 if inversions >= 4 else 1 if inversions >= 2 else 0
        feedback = (
            ["Some points appear out of sequence; try introducing yourself and your education before later details."]
            if penalty else []
        )
        return {
            "order": present,
            "inversions": inversions,
            "penalty": penalty,
            "feedback": feedback,
        }

    def _get_language_tool(self):
        if self.language_tool or self.language_tool_load_failed:
            return self.language_tool
        with self._language_tool_lock:
            if self.language_tool or self.language_tool_load_failed:
                return self.language_tool
            try:
                import language_tool_python

                self.language_tool = language_tool_python.LanguageTool("en-US")
            except Exception as exc:
                self.language_tool_load_failed = True
                LOGGER.warning(
                    "Local LanguageTool is unavailable; using built-in grammar checks: %s",
                    exc,
                )
        return self.language_tool

    @staticmethod
    def _grammar_category(rule_id, category, issue_type):
        combined = f"{rule_id} {category} {issue_type}".lower()
        if "agreement" in combined or "verb" in combined:
            return "subject_verb_agreement"
        if "article" in combined or "determiner" in combined:
            return "article_usage"
        if "preposition" in combined:
            return "preposition_usage"
        if "pronoun" in combined:
            return "pronoun_usage"
        if "tense" in combined:
            return "verb_tense"
        if "punctuation" in combined or "capital" in combined:
            return "writing_mechanics"
        if "style" in combined:
            return "style"
        if "spelling" in combined or "typo" in combined:
            return "spelling"
        return "grammar"

    @staticmethod
    def _severity_for_category(category):
        return "low" if category in {"style", "spelling", "writing_mechanics"} else "medium"

    @staticmethod
    def _is_technical_word(text):
        normalized = text.strip().lower().strip(string.punctuation)
        return normalized in {term.strip() for term in TECHNICAL_TERMS}

    @staticmethod
    def _make_grammar_issue(original, suggestion, category, explanation, start=None):
        return {
            "type": category,
            "original": original,
            "suggestion": suggestion or original,
            "explanation": explanation,
            "severity": "medium" if category != "style" else "low",
            "start": start,
        }

    def _builtin_grammar_issues(self, transcript):
        issues = []
        for pattern, replacements, category, severity in GRAMMAR_RULES:
            for match in pattern.finditer(transcript):
                verb = match.group(1).lower()
                replacement, explanation = replacements[verb]
                if replacement is None:
                    singular = match.group(1)
                    verb_form = {"have": "has", "are": "is", "do": "does"}[verb]
                    replacement = f"{singular} {verb_form}"
                issues.append({
                    "type": category,
                    "original": match.group(0),
                    "suggestion": replacement,
                    "explanation": explanation,
                    "severity": severity,
                    "start": match.start(),
                })
        return issues

    def _language_tool_issues(self, transcript):
        tool = self._get_language_tool()
        if tool is None:
            return []
        try:
            matches = tool.check(transcript)
        except Exception as exc:
            LOGGER.warning(
                "LanguageTool analysis failed; using built-in grammar checks for this score: %s",
                exc,
            )
            return []

        issues = []
        for match in matches:
            offset = int(getattr(match, "offset", 0))
            length = int(getattr(match, "errorLength", 0))
            original = transcript[offset:offset + length]
            if not original or self._is_technical_word(original):
                continue
            replacements = getattr(match, "replacements", []) or []
            suggestion = replacements[0] if replacements else original
            rule_id = getattr(match, "ruleId", "")
            category_name = getattr(match, "category", "")
            issue_type = getattr(match, "ruleIssueType", "")
            category = self._grammar_category(rule_id, category_name, issue_type)
            issues.append({
                "type": category,
                "original": original,
                "suggestion": suggestion,
                "explanation": str(getattr(match, "message", "Review this grammar or language issue.")),
                "severity": self._severity_for_category(category),
                "start": offset,
            })
        return issues

    def _collect_grammar_issues(self, transcript):
        found = self._builtin_grammar_issues(transcript) + self._language_tool_issues(transcript)
        unique = {}
        for issue in found:
            key = (issue["original"].lower(), issue["suggestion"].lower(), issue["type"])
            unique.setdefault(key, issue)
        return sorted(unique.values(), key=lambda issue: issue["start"] or 0)

    @staticmethod
    def _language_quality_metrics(transcript):
        sentences = ScoringEngine._sentences(transcript)
        words = [
            match.group(0).lower().strip(string.punctuation)
            for match in _WORD_RE.finditer(transcript)
            if match.group(0).strip(string.punctuation)
        ]
        unique_words = set(words)
        ttr = len(unique_words) / len(words) if words else 0.0

        long_sentences = [
            sentence for sentence in sentences
            if len(_WORD_RE.findall(sentence)) > 30
        ]
        normalized = [word.lower().strip(string.punctuation) for word in words]
        stop_words = {
            "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
            "i", "in", "is", "it", "of", "on", "or", "the", "this", "to",
            "was", "we", "with", "you",
        }
        repeated_words = [
            word for word, count in Counter(normalized).items()
            if count >= 4 and word not in stop_words
        ]
        phrase_counts = Counter()
        for sentence in sentences:
            tokens = [
                token.lower().strip(string.punctuation)
                for token in _WORD_RE.findall(sentence)
            ]
            for size in (2, 3, 4):
                for index in range(len(tokens) - size + 1):
                    phrase = tuple(tokens[index:index + size])
                    if not set(phrase).issubset(stop_words):
                        phrase_counts[phrase] += 1
        repeated_phrases = [
            " ".join(phrase)
            for phrase, count in phrase_counts.items()
            if count >= 2 and not set(phrase).issubset(stop_words)
        ]
        repeated_phrases = list(dict.fromkeys(repeated_phrases))[:5]

        fragments = []
        complete_sentence_re = re.compile(
            r"\b(?:am|is|are|was|were|be|been|being|have|has|had|do|does|did|"
            r"can|could|will|would|should|must|may|might|work|works|worked|"
            r"study|studies|studied|pursue|pursues|pursuing|develop|developed|"
            r"build|built|use|uses|using|enjoy|enjoys|like|likes|want|wants|"
            r"aspire|aim|plan|completed|earned|received|created|designed)\b",
            re.IGNORECASE,
        )
        for sentence in sentences:
            stripped = sentence.strip().strip(string.punctuation)
            if not stripped:
                continue
            if re.match(r"^(?:hello|hi|good morning|good afternoon|good evening|"
                        r"thank you|thanks)\b", stripped, re.IGNORECASE):
                continue
            if len(_WORD_RE.findall(stripped)) >= 4 and not complete_sentence_re.search(stripped):
                fragments.append(stripped)

        mechanics_issues = []
        for sentence in sentences:
            clean = sentence.strip()
            if clean and clean[0].islower():
                mechanics_issues.append(f"Capitalize the first word: {clean[:50]}")
            if clean and clean[-1] not in ".!?":
                mechanics_issues.append(f"Add ending punctuation: {clean[:50]}")
        return {
            "sentences": sentences,
            "word_count": len(words),
            "ttr": ttr,
            "long_sentences": long_sentences,
            "repeated_words": repeated_words,
            "repeated_phrases": repeated_phrases,
            "fragments": fragments,
            "mechanics_issues": mechanics_issues,
        }

    def score_language_and_grammar(self, transcript, criterion):
        quality = self._language_quality_metrics(transcript)
        issues = self._collect_grammar_issues(transcript)
        severity_penalties = {"low": 0.5, "medium": 1.25, "high": 1.75}
        grammar_score = max(
            0,
            round(
                LANGUAGE_METRIC_WEIGHTS["grammar"]
                - min(sum(severity_penalties.get(issue["severity"], 1.0) for issue in issues), 8),
                2,
            ),
        )
        sentence_penalty = min(len(quality["long_sentences"]) * 0.75, 2.25)
        structure_score = round(max(0, 3 - sentence_penalty), 2)
        ttr_score = round(min(3, quality["ttr"] / 0.55 * 3), 2)
        repetition_penalty = min(
            1.5,
            0.5 * len(quality["repeated_phrases"])
            + 0.25 * len(quality["repeated_words"]),
        )
        repetition_score = round(max(0, 2 - repetition_penalty), 2)
        completeness_penalty = min(len(quality["fragments"]) * 0.5, 2)
        completeness_score = round(max(0, 2 - completeness_penalty), 2)
        mechanics_penalty = min(len(quality["mechanics_issues"]) * 0.25, 1.5)
        mechanics_score = round(max(0, 2 - mechanics_penalty), 2)

        metrics = [
            {
                "metric": "Grammar Score",
                "score": grammar_score,
                "max_score": LANGUAGE_METRIC_WEIGHTS["grammar"],
                "errors": len(issues),
                "issues": issues,
                "feedback": (
                    "No grammar issues were detected."
                    if not issues else f"{len(issues)} potential grammar issue(s) to review."
                ),
            },
            {
                "metric": "Sentence Structure",
                "score": structure_score,
                "max_score": LANGUAGE_METRIC_WEIGHTS["sentence_structure"],
                "long_sentences": quality["long_sentences"],
                "feedback": (
                    "Sentences are within the 30-word review threshold."
                    if not quality["long_sentences"]
                    else f"{len(quality['long_sentences'])} sentence(s) exceed 30 words."
                ),
            },
            {
                "metric": "Vocabulary Richness",
                "score": ttr_score,
                "max_score": LANGUAGE_METRIC_WEIGHTS["vocabulary"],
                "ttr": round(quality["ttr"], 3),
                "unique_words": len(set(
                    word.lower().strip(string.punctuation)
                    for word in _WORD_RE.findall(transcript)
                )),
                "total_words": quality["word_count"],
                "feedback": f"Vocabulary diversity: TTR = {quality['ttr']:.3f}.",
            },
            {
                "metric": "Repetition",
                "score": repetition_score,
                "max_score": LANGUAGE_METRIC_WEIGHTS["repetition"],
                "repeated_words": quality["repeated_words"],
                "repeated_phrases": quality["repeated_phrases"],
                "feedback": (
                    "No notable repeated words or phrases were detected."
                    if not quality["repeated_words"] and not quality["repeated_phrases"]
                    else "Review repeated words or phrases where they do not add meaning."
                ),
            },
            {
                "metric": "Sentence Completeness",
                "score": completeness_score,
                "max_score": LANGUAGE_METRIC_WEIGHTS["completeness"],
                "fragments": quality["fragments"],
                "feedback": (
                    "No likely sentence fragments were detected."
                    if not quality["fragments"]
                    else f"{len(quality['fragments'])} possible sentence fragment(s) need review."
                ),
            },
            {
                "metric": "Writing Mechanics",
                "score": mechanics_score,
                "max_score": LANGUAGE_METRIC_WEIGHTS["mechanics"],
                "issues": quality["mechanics_issues"],
                "feedback": (
                    "Basic capitalization and punctuation look consistent."
                    if not quality["mechanics_issues"]
                    else f"{len(quality['mechanics_issues'])} basic writing-mechanics issue(s) detected."
                ),
            },
        ]
        score = round(sum(metric["score"] for metric in metrics), 2)
        total_weight = criterion["weight"]
        weighted_score = round(score / 20 * total_weight, 2)
        strengths = []
        if grammar_score >= 7:
            strengths.append("Sentences are mostly grammatically sound.")
        if ttr_score >= 2:
            strengths.append("Vocabulary shows useful variety.")
        if not quality["repeated_words"] and not quality["repeated_phrases"]:
            strengths.append("No notable repetition was detected.")
        if not quality["long_sentences"]:
            strengths.append("Sentence lengths are manageable.")

        improvements = []
        if issues:
            improvements.append(f"Review {len(issues)} grammar correction(s) below.")
        if quality["long_sentences"]:
            improvements.append("Break up long sentences so each point is easier to follow.")
        if quality["repeated_words"] or quality["repeated_phrases"]:
            improvements.append("Vary repeated words or phrases where possible.")
        if quality["fragments"]:
            improvements.append("Rewrite incomplete thoughts as complete sentences.")
        if quality["mechanics_issues"]:
            improvements.append("Check capitalization and end punctuation.")

        return {
            "criterion": criterion["name"],
            "weight": total_weight,
            "score": score,
            "max_score": 20,
            "weighted_score": weighted_score,
            "metrics": metrics,
            "language_grammar": {
                "score": score,
                "max_score": 20,
                "issues": issues,
                "strengths": strengths,
                "improvements": improvements,
                "feedback": {
                    "strengths": strengths,
                    "issues": issues,
                    "suggestions": improvements,
                    "summary": (
                        f"Language and grammar score: {score}/20 across grammar, sentence "
                        "structure, vocabulary, repetition, completeness, and mechanics."
                    ),
                },
            },
        }
    
    def score_metric(self, transcript, metric, criterion_name, wpm, word_count):
        """Score a single metric"""
        metric_name = metric["name"]
        
        if metric_name == "Salutation Level":
            return self.score_salutation(transcript, metric)
        elif metric_name == "Keyword Presence":
            return self.score_keyword_presence(transcript, metric)
        elif metric_name == "Flow":
            return self.score_flow(transcript, metric)
        elif metric_name == "Words Per Minute":
            return self.score_wpm(wpm, metric)
        elif metric_name == "Grammar Score":
            return self.score_grammar(transcript, metric, word_count)
        elif metric_name == "Vocabulary Richness":
            return self.score_vocabulary(transcript, metric)
        elif metric_name == "Filler Word Rate":
            return self.score_filler_words(transcript, metric, word_count)
        elif metric_name == "Sentiment/Positivity":
            return self.score_sentiment(transcript, metric)
        else:
            return {"metric": metric_name, "score": 0, "feedback": "Unknown metric"}
    
    def score_salutation(self, transcript, metric):
        """Rule-based + NLP: Score salutation level"""
        transcript_lower = transcript.lower()
        first_sentence = transcript.split('.')[0] if '.' in transcript else transcript[:100]
        
        matched_level = "No Salutation"
        score = 0
        keywords_found = []
        
        # Check keywords (rule-based)
        for level_data in reversed(metric["scoring"]):  # Check from highest to lowest
            for keyword in level_data["keywords"]:
                if keyword.lower() in transcript_lower[:150]:  # Check first 150 chars
                    matched_level = level_data["level"]
                    score = level_data["score"]
                    keywords_found.append(keyword)
                    break
            if score > 0:
                break
        
        # NLP-based: Semantic similarity with greeting patterns
        if score == 0:
            model = self.get_model()
            if model is None:
                return {
                    "metric": "Salutation Level",
                    "score": score,
                    "max_score": metric["max_score"],
                    "level": matched_level,
                    "keywords_found": keywords_found,
                    "feedback": f"Salutation: {matched_level} (Score: {score}/{metric['max_score']})"
                }

            if self._greeting_embeddings is None:
                self._greeting_embeddings = model.encode(self.greeting_patterns)

            first_sent_embedding = model.encode([first_sentence])
            from sklearn.metrics.pairwise import cosine_similarity
            similarities = cosine_similarity(first_sent_embedding, self._greeting_embeddings)[0]
            max_similarity = max(similarities)
            
            if max_similarity > 0.5:
                score = min(int(max_similarity * 5), 5)
                matched_level = "Semantic Match"
        
        return {
            "metric": "Salutation Level",
            "score": score,
            "max_score": metric["max_score"],
            "level": matched_level,
            "keywords_found": keywords_found,
            "feedback": f"Salutation: {matched_level} (Score: {score}/{metric['max_score']})"
        }
    
    def score_keyword_presence(self, transcript, metric):
        """Rule-based + NLP: Score keyword presence"""
        transcript_lower = transcript.lower()
        score = 0
        keywords_found = {}
        
        # Must-have keywords
        for item in metric["must_have"]:
            found = False
            matched_keywords = []
            for kw in item["keywords"]:
                if kw.lower() in transcript_lower:
                    found = True
                    matched_keywords.append(kw)
            
            if found:
                score += item["score"]
                keywords_found[item["keyword"]] = {
                    "found": True,
                    "keywords": matched_keywords,
                    "score": item["score"]
                }
            else:
                keywords_found[item["keyword"]] = {
                    "found": False,
                    "score": 0
                }
        
        # Good-to-have keywords
        for item in metric["good_to_have"]:
            found = False
            matched_keywords = []
            for kw in item["keywords"]:
                if kw.lower() in transcript_lower:
                    found = True
                    matched_keywords.append(kw)
            
            if found:
                score += item["score"]
                keywords_found[item["keyword"]] = {
                    "found": True,
                    "keywords": matched_keywords,
                    "score": item["score"]
                }
            else:
                keywords_found[item["keyword"]] = {
                    "found": False,
                    "score": 0
                }
        
        return {
            "metric": "Keyword Presence",
            "score": score,
            "max_score": metric["max_score"],
            "keywords_found": keywords_found,
            "feedback": f"Found {sum(1 for k in keywords_found.values() if k['found'])}/{len(keywords_found)} required elements"
        }
    
    def score_flow(self, transcript, metric):
        """NLP-based: Score flow/structure"""
        # Simple heuristic: check if transcript follows logical order
        # Salutation → Name → Details → Closing
        
        sentences = [s.strip() for s in re.split('[.!?]', transcript) if s.strip()]
        if not sentences:
            return {
                "metric": "Flow",
                "score": 0,
                "max_score": metric["max_score"],
                "feedback": "Add a clear opening, personal details, and closing."
            }
        
        flow_score = 0
        feedback = []
        
        # Check salutation in first sentence
        if any(word in sentences[0].lower() for word in ['hello', 'hi', 'good', 'greetings']):
            flow_score += 1
            feedback.append("Good opening salutation")
        
        # Check name in first 2 sentences
        first_two = ' '.join(sentences[:2]).lower()
        if any(word in first_two for word in ['name', 'myself', 'i am', "i'm"]):
            flow_score += 2
            feedback.append("Name introduced early")
        
        # Check closing in last sentence
        if any(word in sentences[-1].lower() for word in ['thank', 'thanks', 'pleasure', 'nice']):
            flow_score += 2
            feedback.append("Has proper closing")
        
        # Normalize to metric's max score
        score = min(flow_score, metric["max_score"])
        
        return {
            "metric": "Flow",
            "score": score,
            "max_score": metric["max_score"],
            "feedback": "; ".join(feedback) if feedback else "Structure could be improved"
        }
    
    def score_wpm(self, wpm, metric):
        """Rule-based: Score words per minute"""
        if wpm is None:
            return {
                "metric": "Words Per Minute",
                "score": 0,
                "max_score": metric["max_score"],
                "wpm": None,
                "feedback": "Duration not provided, cannot calculate WPM"
            }
        
        score = 0
        level = "Unknown"
        assessed_wpm = math.floor(wpm + 0.5)
        
        for range_data in metric["scoring"]:
            min_wpm, max_wpm = range_data["range"]
            if min_wpm <= assessed_wpm <= max_wpm:
                score = range_data["score"]
                level = range_data["level"]
                break
        
        return {
            "metric": "Words Per Minute",
            "score": score,
            "max_score": metric["max_score"],
            "wpm": round(wpm, 2),
            "level": level,
            "feedback": f"Speech rate: {round(wpm, 2)} WPM ({level})"
        }
    
    def score_grammar(self, transcript, metric, word_count):
        """Rule-based: Score grammar using simple heuristics"""
        # Simple grammar checks (in real implementation, use language_tool_python)
        errors = 0
        
        # Basic checks
        sentences = [s.strip() for s in re.split('[.!?]', transcript) if s.strip()]
        
        for sentence in sentences:
            # Check if sentence starts with capital letter
            if sentence and not sentence[0].isupper():
                errors += 1
            
            # Check for common errors (simple heuristics)
            if ' i ' in sentence.lower() and ' I ' not in sentence:
                errors += 1
        
        # Calculate grammar score
        errors_per_100 = (errors / word_count) * 100 if word_count > 0 else 0
        grammar_score_value = max(0, 1 - min(errors_per_100 / 10, 1))
        
        # Map to score range
        score = 0
        for range_data in metric["scoring"]:
            min_val, max_val = range_data["range"]
            if min_val <= grammar_score_value <= max_val:
                score = range_data["score"]
                break
        
        return {
            "metric": "Grammar Score",
            "score": score,
            "max_score": metric["max_score"],
            "errors": errors,
            "errors_per_100": round(errors_per_100, 2),
            "grammar_score_value": round(grammar_score_value, 3),
            "feedback": f"Grammar quality: {round(grammar_score_value * 100, 1)}% ({errors} errors detected)"
        }
    
    def score_vocabulary(self, transcript, metric):
        """Rule-based: Score vocabulary richness using TTR"""
        words = transcript.lower().split()
        unique_words = set(words)
        
        ttr = len(unique_words) / len(words) if words else 0
        
        score = 0
        for range_data in metric["scoring"]:
            min_val, max_val = range_data["range"]
            if min_val <= ttr <= max_val:
                score = range_data["score"]
                break
        
        return {
            "metric": "Vocabulary Richness",
            "score": score,
            "max_score": metric["max_score"],
            "ttr": round(ttr, 3),
            "unique_words": len(unique_words),
            "total_words": len(words),
            "feedback": f"Vocabulary diversity: TTR = {round(ttr, 3)} ({len(unique_words)} unique words)"
        }
    
    def score_filler_words(self, transcript, metric, word_count):
        """Rule-based: Score filler word rate"""
        transcript_lower = transcript.lower()
        filler_words = metric["filler_words"]
        
        filler_count = 0
        found_fillers = []
        
        for filler in filler_words:
            # Count occurrences
            count = transcript_lower.count(f" {filler} ") + transcript_lower.count(f" {filler},")
            if transcript_lower.startswith(f"{filler} "):
                count += 1
            if count > 0:
                filler_count += count
                found_fillers.append(f"{filler}({count})")
        
        filler_rate = (filler_count / word_count) * 100 if word_count > 0 else 0
        
        score = 0
        for range_data in metric["scoring"]:
            min_val, max_val = range_data["range"]
            if min_val <= filler_rate <= max_val:
                score = range_data["score"]
                break
        
        return {
            "metric": "Filler Word Rate",
            "score": score,
            "max_score": metric["max_score"],
            "filler_count": filler_count,
            "filler_rate": round(filler_rate, 2),
            "found_fillers": found_fillers,
            "feedback": f"Filler word rate: {round(filler_rate, 2)}% ({filler_count} fillers found)"
        }
    
    def score_sentiment(self, transcript, metric):
        """NLP-based: Score sentiment/positivity"""
        # Using simple word-based sentiment (in production, use VADER)
        positive_words = [
            'good', 'great', 'excellent', 'wonderful', 'amazing', 'love', 'enjoy',
            'excited', 'happy', 'blessed', 'grateful', 'fortunate', 'delighted',
            'passionate', 'enthusiastic', 'interested', 'fascinating', 'beautiful'
        ]
        
        negative_words = [
            'bad', 'terrible', 'awful', 'hate', 'dislike', 'boring', 'sad',
            'difficult', 'hard', 'struggle', 'problem', 'unfortunately'
        ]
        
        words = transcript.lower().split()
        positive_count = sum(1 for word in words if word in positive_words)
        negative_count = sum(1 for word in words if word in negative_words)
        
        # Calculate sentiment score (0-1)
        total_sentiment_words = positive_count + negative_count
        if total_sentiment_words > 0:
            sentiment_score = positive_count / total_sentiment_words
        else:
            sentiment_score = 0.5  # Neutral
        
        # Adjust based on overall tone
        if positive_count > 0:
            sentiment_score = min(sentiment_score + 0.2, 1.0)
        
        score = 0
        for range_data in metric["scoring"]:
            min_val, max_val = range_data["range"]
            if min_val <= sentiment_score <= max_val:
                score = range_data["score"]
                break
        
        return {
            "metric": "Sentiment/Positivity",
            "score": score,
            "max_score": metric["max_score"],
            "sentiment_score": round(sentiment_score, 3),
            "positive_words": positive_count,
            "negative_words": negative_count,
            "feedback": f"Sentiment: {round(sentiment_score * 100, 1)}% positive ({positive_count} positive words)"
        }
