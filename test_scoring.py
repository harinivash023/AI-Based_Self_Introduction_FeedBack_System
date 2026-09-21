"""
Test script to verify the scoring system works correctly
"""
from rubric_parser import RubricParser
from scoring_engine import ScoringEngine
import json

def test_scoring():
    print("="*80)
    print("Communication Skills Scoring Tool - Test")
    print("="*80)
    print()
    
    # Initialize
    print("1. Initializing rubric parser...")
    parser = RubricParser()
    print("   OK Rubric parser initialized")
    
    print("\n2. Loading rubrics...")
    rubrics = parser.get_rubrics()
    print(f"   OK Loaded {len(rubrics['criteria'])} criteria")
    
    print("\n3. Initializing scoring engine...")
    scorer = ScoringEngine(rubrics)
    print("   OK Scoring engine ready")
    
    # Get sample transcript
    print("\n4. Loading sample transcript...")
    transcript = parser.get_sample_transcript()
    print(f"   OK Transcript loaded ({len(transcript)} characters)")
    print(f"\n   Sample preview:")
    print(f"   {transcript[:200]}...")
    
    # Score the transcript
    print("\n5. Scoring transcript...")
    results = scorer.calculate_score(transcript, duration_seconds=52)
    print("   OK Scoring complete!")
    
    # Display results
    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)
    
    print(f"\nOverall Score: {results['overall_score']}/100")
    print(f"Word Count: {results['word_count']}")
    if results['metadata']['wpm']:
        print(f"Words Per Minute: {results['metadata']['wpm']:.2f}")
    
    print("\n" + "-"*80)
    print("Per-Criterion Scores:")
    print("-"*80)
    
    for criterion in results['criteria_scores']:
        print(f"\n{criterion['criterion']}: {criterion['weighted_score']}/{criterion['weight']}")
        print(f"  (Raw score: {criterion['score']}/{criterion['max_score']})")
        
        for metric in criterion['metrics']:
            print(f"  - {metric['metric']}: {metric['score']}/{metric['max_score']}")
            print(f"    {metric['feedback']}")
    
    print("\n" + "="*80)
    
    # Save results to JSON
    print("\n6. Saving results to test_results.json...")
    with open('test_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("   OK Results saved!")
    
    print("\n" + "="*80)
    print("Test completed successfully!")
    print("="*80)
    
    return results

if __name__ == "__main__":
    test_scoring()
