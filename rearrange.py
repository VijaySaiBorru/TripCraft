import numpy as np
from sentence_transformers import SentenceTransformer
from numpy.linalg import norm

# 1. Load the embedding model
embedder = SentenceTransformer('all-mpnet-base-v2')

def cosine_sim(a, b):
    """Calculates cosine similarity between two vectors."""
    return np.dot(a, b) / (norm(a) * norm(b))

def calculate_rgpa(persona_text, itinerary_entities, lambda_penalty=0.5):
    """
    persona_text: String (e.g., "adventure traveler, luxury stays...")
    itinerary_entities: List of dicts, each with 'pros' and 'cons' strings
    """
    # Embed the persona once
    v_persona = embedder.encode(persona_text)
    
    entity_scores = []
    
    # Loop through every place in the generated itinerary
    for entity in itinerary_entities:
        # Your script saved pros/cons with '|', let's replace with '. ' to make it a paragraph
        pros_text = str(entity['pros']).replace('|', '. ')
        cons_text = str(entity['cons']).replace('|', '. ')
        
        # Embed the combined pros and cons
        v_pros = embedder.encode(pros_text)
        v_cons = embedder.encode(cons_text)
        
        # Calculate cosine similarities
        sim_pros = cosine_sim(v_persona, v_pros)
        sim_cons = cosine_sim(v_persona, v_cons)
        
        # Apply the math formula for this single entity
        entity_score = sim_pros - lambda_penalty * max(0, sim_cons)
        entity_scores.append(entity_score)
    
    # The final RGPA is the average of all entity scores in the itinerary
    final_rgpa_score = np.mean(entity_scores)
    
    return final_rgpa_score

# ==========================================
# Example Usage:
# ==========================================
persona = "adventure traveler, nature exploration, economical stays"

# A 2-entity itinerary (1 Hotel, 1 Attraction)
itinerary = [
    {
        "name": "Budget San Diego House",
        "pros": "Excellent value for price|Safe neighborhood|Clean",
        "cons": "Not close to downtown|Walk to transit is 15 mins"
    },
    {
        "name": "Sea Lion Beach",
        "pros": "Stunning beach views|Observe wildlife|Hiking trails",
        "cons": "Strong odor|Dangerous waves"
    }
]

score = calculate_rgpa(persona, itinerary)
print(f"Final Itinerary RGPA Score: {score}")