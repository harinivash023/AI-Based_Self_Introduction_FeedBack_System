"""
Rubric Parser - Extracts rubrics and scoring criteria from Excel file
"""
import pandas as pd
import json

class RubricParser:
    def __init__(self, excel_file='Case study for interns.xlsx'):
        self.excel_file = excel_file
        self.rubrics = None
        self.sample_transcript = None
        self.parse_excel()
    
    def parse_excel(self):
        """Parse the Excel file and extract rubrics"""
        df = pd.read_excel(self.excel_file, sheet_name='Rubrics', header=None)
        
        # Extract sample transcript (row 7, column 2)
        self.sample_transcript = str(df.iloc[7, 2]) if pd.notna(df.iloc[7, 2]) else ""
        
        # Extract rubrics structure
        self.rubrics = {
            "criteria": [
                {
                    "name": "Content & Structure",
                    "weight": 40,
                    "metrics": [
                        {
                            "name": "Salutation Level",
                            "max_score": 5,
                            "weight": 5,
                            "scoring": [
                                {"level": "No Salutation", "keywords": [], "score": 0},
                                {"level": "Normal", "keywords": ["Hi", "Hello"], "score": 2},
                                {"level": "Good", "keywords": ["Good Morning", "Good Afternoon", "Good Evening", "Good Day", "Hello everyone"], "score": 4},
                                {"level": "Excellent", "keywords": ["I am excited to introduce", "Feeling great", "excited", "pleasure", "delighted"], "score": 5}
                            ]
                        },
                        {
                            "name": "Keyword Presence",
                            "max_score": 30,
                            "weight": 30,
                            "must_have": [
                                {"keyword": "name", "keywords": ["name", "myself", "I am", "I'm"], "score": 4},
                                {"keyword": "age", "keywords": ["year", "years old", "age"], "score": 4},
                                {"keyword": "school/class", "keywords": ["school", "class", "grade", "studying"], "score": 4},
                                {"keyword": "family", "keywords": ["family", "mother", "father", "brother", "sister", "parents"], "score": 4},
                                {"keyword": "hobbies", "keywords": ["hobby", "hobbies", "like", "enjoy", "love", "play", "playing", "interest"], "score": 4}
                            ],
                            "good_to_have": [
                                {"keyword": "about_family", "keywords": ["kind", "loving", "caring", "supportive"], "score": 2},
                                {"keyword": "origin", "keywords": ["from", "belong", "native"], "score": 2},
                                {"keyword": "ambition", "keywords": ["goal", "dream", "ambition", "want to be", "aspire"], "score": 2},
                                {"keyword": "unique_fact", "keywords": ["fun fact", "interesting", "unique", "special"], "score": 2},
                                {"keyword": "achievements", "keywords": ["achievement", "strength", "good at", "excel"], "score": 2}
                            ]
                        },
                        {
                            "name": "Flow",
                            "max_score": 5,
                            "weight": 5,
                            "description": "Order: Salutation → Name → Mandatory details → Optional Details → Closing"
                        }
                    ]
                },
                {
                    "name": "Speech Rate",
                    "weight": 10,
                    "metrics": [
                        {
                            "name": "Words Per Minute",
                            "max_score": 10,
                            "weight": 10,
                            "scoring": [
                                {"range": [161, 9999], "level": "Too Fast", "score": 2},
                                {"range": [141, 160], "level": "Fast", "score": 6},
                                {"range": [111, 140], "level": "Ideal", "score": 10},
                                {"range": [81, 110], "level": "Slow", "score": 6},
                                {"range": [0, 80], "level": "Too Slow", "score": 2}
                            ]
                        }
                    ]
                },
                {
                    "name": "Language & Grammar",
                    "weight": 20,
                    "metrics": [
                        {
                            "name": "Grammar Score",
                            "max_score": 10,
                            "weight": 10,
                            "description": "Grammar Score = 1 - min(errors per 100 words / 10, 1)",
                            "scoring": [
                                {"range": [0.9, 1.0], "score": 10},
                                {"range": [0.7, 0.89], "score": 8},
                                {"range": [0.5, 0.69], "score": 6},
                                {"range": [0.3, 0.49], "score": 4},
                                {"range": [0, 0.29], "score": 2}
                            ]
                        },
                        {
                            "name": "Vocabulary Richness",
                            "max_score": 10,
                            "weight": 10,
                            "description": "TTR = Distinct words / Total words",
                            "scoring": [
                                {"range": [0.9, 1.0], "score": 10},
                                {"range": [0.7, 0.89], "score": 8},
                                {"range": [0.5, 0.69], "score": 6},
                                {"range": [0.3, 0.49], "score": 4},
                                {"range": [0, 0.29], "score": 2}
                            ]
                        }
                    ]
                },
                {
                    "name": "Clarity",
                    "weight": 15,
                    "metrics": [
                        {
                            "name": "Filler Word Rate",
                            "max_score": 15,
                            "weight": 15,
                            "filler_words": ["um", "uh", "like", "you know", "so", "actually", "basically", "right", "i mean", "well", "kinda", "sort of", "okay", "hmm", "ah"],
                            "description": "Filler Word Rate = (Number of filler words / Total words) × 100",
                            "scoring": [
                                {"range": [0, 3], "score": 15},
                                {"range": [4, 6], "score": 12},
                                {"range": [7, 9], "score": 9},
                                {"range": [10, 12], "score": 6},
                                {"range": [13, 999], "score": 3}
                            ]
                        }
                    ]
                },
                {
                    "name": "Engagement",
                    "weight": 15,
                    "metrics": [
                        {
                            "name": "Sentiment/Positivity",
                            "max_score": 15,
                            "weight": 15,
                            "description": "VADER sentiment analysis (positive probability 0-1)",
                            "scoring": [
                                {"range": [0.9, 1.0], "score": 15},
                                {"range": [0.7, 0.89], "score": 12},
                                {"range": [0.5, 0.69], "score": 9},
                                {"range": [0.3, 0.49], "score": 6},
                                {"range": [0, 0.29], "score": 3}
                            ]
                        }
                    ]
                }
            ]
        }
    
    def get_rubrics(self):
        """Return the parsed rubrics"""
        return self.rubrics
    
    def get_sample_transcript(self):
        """Return the sample transcript"""
        return self.sample_transcript
    
    def save_rubrics_json(self, output_file='rubrics.json'):
        """Save rubrics to JSON file"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.rubrics, f, indent=2, ensure_ascii=False)
        print(f"Rubrics saved to {output_file}")

if __name__ == "__main__":
    parser = RubricParser()
    print("Sample Transcript:")
    print(parser.get_sample_transcript())
    print("\n" + "="*80 + "\n")
    
    rubrics = parser.get_rubrics()
    print("Rubrics extracted successfully!")
    print(json.dumps(rubrics, indent=2))
    
    # Save to JSON
    parser.save_rubrics_json()
