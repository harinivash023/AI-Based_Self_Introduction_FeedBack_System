"""
Scoring Engine - Combines rule-based, NLP-based, and rubric-driven scoring
"""
import os
import re

os.environ.setdefault("USE_TF", "0")

class ScoringEngine:
    def __init__(self, rubrics):
        self.rubrics = rubrics
        self.model = None
        self.model_load_failed = False

    def get_model(self):
        """Load the semantic model only when a metric needs it."""
        if self.model or self.model_load_failed:
            return self.model

        try:
            print("Loading sentence transformer model...")
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            print("Model loaded successfully!")
        except Exception as exc:
            self.model_load_failed = True
            print(f"Semantic model unavailable, continuing with rule-based scoring: {exc}")
        return self.model
    
    def calculate_score(self, transcript, duration_seconds=None):
        """
        Main scoring function
        Returns: dict with overall score and per-criterion scores
        """
        words = transcript.split()
        word_count = len(words)
        
        # Calculate WPM if duration provided
        wpm = None
        if duration_seconds:
            wpm = (word_count / duration_seconds) * 60
        
        results = {
            "overall_score": 0,
            "word_count": word_count,
            "criteria_scores": [],
            "metadata": {
                "wpm": wpm,
                "duration_seconds": duration_seconds
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

            greeting_patterns = [
                "Hello everyone, I am happy to introduce myself",
                "Good morning, I am excited to be here",
                "Hi, my name is"
            ]
            
            first_sent_embedding = model.encode([first_sentence])
            pattern_embeddings = model.encode(greeting_patterns)
            from sklearn.metrics.pairwise import cosine_similarity
            similarities = cosine_similarity(first_sent_embedding, pattern_embeddings)[0]
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
        
        for range_data in metric["scoring"]:
            min_wpm, max_wpm = range_data["range"]
            if min_wpm <= wpm <= max_wpm:
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
