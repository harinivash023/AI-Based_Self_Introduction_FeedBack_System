"""Shared rubric definition and sample-transcript loader."""
import pandas as pd
import json
import os

class RubricParser:
    def __init__(self, excel_file=None):
        self.excel_file = excel_file or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'Case study for interns.xlsx'
        )
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
                        {"name": "Greeting", "max_score": 4, "weight": 4, "importance": "required"},
                        {"name": "Name / Personal Introduction", "max_score": 5, "weight": 5, "importance": "required"},
                        {"name": "Education", "max_score": 6, "weight": 6, "importance": "required"},
                        {"name": "Technical Skills", "max_score": 5, "weight": 5, "importance": "recommended"},
                        {"name": "Projects", "max_score": 4, "weight": 4, "importance": "recommended"},
                        {"name": "Internship / Work Experience", "max_score": 3, "weight": 3, "importance": "optional"},
                        {"name": "Achievements / Certifications", "max_score": 2, "weight": 2, "importance": "optional"},
                        {"name": "Career Goal / Role Interest", "max_score": 3, "weight": 3, "importance": "recommended"},
                        {"name": "Closing", "max_score": 3, "weight": 3, "importance": "recommended"},
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
                        {"name": "Grammar Score", "max_score": 8, "weight": 8},
                        {"name": "Sentence Structure", "max_score": 3, "weight": 3},
                        {"name": "Vocabulary Richness", "max_score": 3, "weight": 3},
                        {"name": "Repetition", "max_score": 2, "weight": 2},
                        {"name": "Sentence Completeness", "max_score": 2, "weight": 2},
                        {"name": "Writing Mechanics", "max_score": 2, "weight": 2},
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
