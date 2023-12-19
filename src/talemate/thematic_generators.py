import random

__all__ = ["ThematicGenerator"]

# ABSTRACT ARTISTIC

abstract_artistic_prefixes = [
    "Joyful", "Sorrowful", "Raging", "Serene", "Melancholic",
    "Windy", "Earthy", "Fiery", "Watery", "Skybound",
    "Starry", "Eclipsed", "Cometary", "Nebulous", "Voidlike",
    "Springtime", "Summery", "Autumnal", "Wintry", "Monsoonal",
    "Dawnlike", "Dusky", "Midnight", "Noonday", "Twilight",
    "Melodic", "Harmonic", "Rhythmic", "Crescendoing", "Silent",
    "Existential", "Chaotic", "Orderly", "Free", "Destined",
    "Crimson", "Azure", "Emerald", "Onyx", "Golden",
]

abstract_artistic_suffixes = [
    "Sonata", "Mural", "Ballet", "Haiku", "Symphony",
    "Storm", "Blossom", "Quake", "Tide", "Aurora",
    "Voyage", "Ascent", "Descent", "Crossing", "Quest",
    "Enchantment", "Vision", "Awakening", "Binding", "Transformation",
    "Weaving", "Sculpting", "Forging", "Painting", "Composing",
    "Reflection", "Question", "Insight", "Theory", "Revelation",
    "Prayer", "Meditation", "Revelation", "Ritual", "Pilgrimage",
    "Laughter", "Tears", "Sigh", "Shiver", "Whisper"
]

# PERSONALITY

personality = [
    "Adventurous", "Ambitious", "Amiable", "Amusing", "Articulate",
    "Assertive", "Attentive", "Bold", "Brave", "Calm",
    "Capable", "Careful", "Caring", "Cautious", "Charming",
    "Cheerful", "Clever", "Confident", "Conscientious", "Considerate",
    "Cooperative", "Courageous", "Courteous", "Creative", "Curious",
    "Daring", "Decisive", "Determined", "Diligent", "Diplomatic",
    "Discreet", "Dynamic", "Easygoing", "Efficient", "Energetic",
    "Enthusiastic", "Fair", "Faithful", "Fearless", "Forceful",
    "Forgiving", "Frank", "Friendly", "Funny", "Generous",
    "Gentle", "Good", "Hardworking", "Helpful", "Honest",
    "Honorable", "Humorous", "Idealistic", "Imaginative", "Impartial",
    "Independent", "Intelligent", "Intuitive", "Inventive", "Kind",
    "Lively", "Logical", "Loving", "Loyal", "Modest",
    "Neat", "Nice", "Optimistic", "Passionate", "Patient",
    "Persistent", "Philosophical", "Placid", "Plucky", "Polite",
    "Powerful", "Practical", "Proactive", "Quick", "Quiet",
    "Rational", "Realistic", "Reliable", "Reserved", "Resourceful",
    "Respectful", "Responsible", "Romantic", "Self-confident", "Self-disciplined",
    "Sensible", "Sensitive", "Shy", "Sincere", "Sociable",
    "Straightforward", "Sympathetic", "Thoughtful", "Tidy", "Tough",
    "Trustworthy", "Unassuming", "Understanding", "Versatile", "Warmhearted",
    "Willing", "Wise", "Witty"
]

# BERRY DESSERT

berry_prefixes = [
    "Blueberry", "Strawberry", "Raspberry", "Blackberry", "Cranberry",
    "Boysenberry", "Elderberry", "Gooseberry", "Huckleberry", "Lingonberry",
    "Mulberry", "Salmonberry", "Cloudberry"
]

dessert_suffixes = [
    "Muffin", "Pie", "Jam", "Scone", "Tart",
    "Crumble", "Cobbler", "Crisp", "Pudding", "Cake",
    "Bread", "Butter", "Sauce", "Syrup"
]

# HUMAN ETHNICITY

ethnicities = [
    "African", 
    "Arab", 
    "Asian", 
    "European",
    "Scaninavian",
    "East European",
    "Indian",
    "Latin American", 
    "North American", 
    "South American"
]

# HUMAN NAMES, FEMALE, 20 PER ETHNICITY

human_names_female = {
    "African": [
        "Abebi", "Abeni", "Abimbola", "Abioye", "Abrihet",
        "Adanna", "Adanne", "Adesina", "Adhiambo", "Adjoa",
        "Adwoa", "Afia", "Afiya", "Afolake", "Afolami",
        "Afua", "Agana", "Agbenyaga", "Aisha", "Akachi"
    ],
    "Arab": [
        "Aaliyah", "Aisha", "Amal", "Amina", "Amira",
        "Fatima", "Habiba", "Halima", "Hana", "Huda",
        "Jamilah", "Jasmin", "Layla", "Leila", "Lina",
        "Mariam", "Maryam", "Nadia", "Naima", "Nour"
    ],
    "Asian": [
        "Aiko", "Akari", "Akemi", "Akiko", "Aki",
        "Ayako", "Chieko", "Chika", "Chinatsu", "Chiyoko",
        "Eiko", "Emi", "Eri", "Etsuko", "Fumiko",
        "Hana", "Haru", "Harumi", "Hikari", "Hina"
    ],
    "European": [
        "Adelina", "Adriana", "Alessia", "Alexandra", "Alice",
        "Alina", "Amalia", "Amelia", "Anastasia", "Anca",
        "Andreea", "Aneta", "Aniela", "Anita", "Anna",
        "Antonia", "Ariana", "Aurelia", "Beatrice", "Bianca"
    ],
    "Scaninavian": [
        "Aase", "Aina", "Alfhild", "Ane", "Anja",
        "Astrid", "Birgit", "Bodil", "Borghild", "Dagmar",
        "Elin", "Ellinor", "Elsa", "Else", "Embla",
        "Emma", "Erika", "Freja", "Gerd", "Gudrun"
    ],
    "East European": [
        "Adela", "Adriana", "Agata", "Alina", "Ana",
        "Anastasia", "Anca", "Andreea", "Aneta", "Aniela",
        "Anita", "Anna", "Antonia", "Ariana", "Aurelia",
        "Beatrice", "Bianca", "Camelia", "Carina", "Carmen"
    ],
    "Indian": [
        "Aarushi", "Aditi", "Aishwarya", "Amrita", "Ananya",
        "Anika", "Anjali", "Anushka", "Aparna", "Arya",
        "Avani", "Chandni", "Darshana", "Deepika", "Devika",
        "Diya", "Gauri", "Gayatri", "Isha", "Ishani"
    ],
    "Latin American": [
        "Adriana", "Alejandra", "Alicia", "Ana", "Andrea",
        "Angela", "Antonia", "Aurora", "Beatriz", "Camila",
        "Carla", "Carmen", "Catalina", "Clara", "Cristina",
        "Daniela", "Diana", "Elena", "Emilia", "Eva"
    ],
    "North American": [
        "Abigail", "Addison", "Amelia", "Aria", "Aurora",
        "Avery", "Charlotte", "Ella", "Elizabeth", "Emily",
        "Emma", "Evelyn", "Grace", "Harper", "Isabella",
        "Layla", "Lily", "Mia", "Olivia", "Sophia"
    ], 
    "South American": [
        "Alessandra", "Ana", "Antonia", "Bianca", "Camila",
        "Carla", "Carolina", "Clara", "Daniela", "Elena",
        "Emilia", "Fernanda", "Gabriela", "Isabella", "Julia",
        "Laura", "Luisa", "Maria", "Mariana", "Sofia"
    ],
}

# HUMAN NAMES, MALE, 20 PER ETHNICITY

human_names_male = {
    "African": [
        "Ababuo", "Abdalla", "Abdul", "Abdullah", "Abel",
        "Abidemi", "Abimbola", "Abioye", "Abubakar", "Ade",
        "Adeben", "Adegoke", "Adisa", "Adnan", "Adofo",
        "Adom", "Adwin", "Afolabi", "Afolami", "Afolayan"
    ],
    "Arab": [
        "Abdul", "Abdullah", "Ahmad", "Ahmed", "Ali",
        "Amir", "Anwar", "Bilal", "Elias", "Emir",
        "Faris", "Hassan", "Hussein", "Ibrahim", "Imran",
        "Isa", "Khalid", "Mohammed", "Mustafa", "Omar"
    ],
    "Asian": [
        "Akio", "Akira", "Akiyoshi", "Amane", "Aoi",
        "Arata", "Asahi", "Asuka", "Atsushi", "Daichi",
        "Daiki", "Daisuke", "Eiji", "Haru", "Haruki",
        "Haruto", "Hayato", "Hibiki", "Hideaki", "Hideo"
    ],
    "European": [
        "Adrian", "Alexandru", "Andrei", "Anton", "Bogdan",
        "Cristian", "Daniel", "David", "Dorian", "Dragos",
        "Eduard", "Florin", "Gabriel", "George", "Ion",
        "Iulian", "Lucian", "Marius", "Mihai", "Nicolae"
    ],
    "Scaninavian": [
        "Aage", "Aksel", "Alf", "Anders", "Arne",
        "Asbjorn", "Bjarne", "Bo", "Carl", "Christian",
        "Einar", "Elias", "Erik", "Finn", "Frederik",
        "Gunnar", "Gustav", "Hans", "Harald", "Henrik"
    ],
    "East European": [
        "Adrian", "Alexandru", "Andrei", "Anton", "Bogdan",
        "Cristian", "Daniel", "David", "Dorian", "Dragos",
        "Eduard", "Florin", "Gabriel", "George", "Ion",
        "Iulian", "Lucian", "Marius", "Mihai", "Nicolae"
    ],
    "Indian": [
        "Aarav", "Aayush", "Aditya", "Aman", "Amit",
        "Anand", "Anil", "Anirudh", "Anish", "Anuj",
        "Arjun", "Arun", "Aryan", "Ashish", "Ashok",
        "Ayush", "Deepak", "Dev", "Dhruv", "Ganesh"
    ],
    "Latin American": [
        "Alejandro", "Andres", "Antonio", "Carlos", "Cesar",
        "Cristian", "Daniel", "David", "Diego", "Eduardo",
        "Emiliano", "Esteban", "Fernando", "Francisco", "Gabriel",
        "Gustavo", "Javier", "Jesus", "Jorge", "Jose"
    ],
    "North American": [
        "Aiden", "Alexander", "Benjamin", "Carter", "Daniel",
        "Elijah", "Ethan", "Henry", "Jackson", "Jacob",
        "James", "Jayden", "John", "Liam", "Logan",
        "Lucas", "Mason", "Michael", "Noah", "Oliver"
    ],
    "South American": [
        "Alejandro", "Andres", "Antonio", "Carlos", "Cesar",
        "Cristian", "Daniel", "David", "Diego", "Eduardo",
        "Emiliano", "Esteban", "Fernando", "Francisco", "Gabriel",
        "Gustavo", "Javier", "Jesus", "Jorge", "Jose"
    ],
}

# ACTOR NAME COLOR

actor_name_colors = [
    "#F08080", "#FFD700", "#90EE90", "#ADD8E6", "#DDA0DD",
    "#FFB6C1", "#FAFAD2", "#D3D3D3", "#B0E0E6", "#FFDEAD"
]

class ThematicGenerator:
    
    def __init__(self, seed:int=None):
        self.seed = seed
        self.custom_lists = {}
        
    def _generate(self, prefixes:list[str], suffixes:list[str]):
        try:
            random.seed(self.seed)
            if prefixes and suffixes:
                return (random.choice(prefixes) + " " + random.choice(suffixes)).strip()
            else:
                return random.choice(prefixes or suffixes)
            
        finally:
            random.seed()

    def generate(self, *list_names) -> str:
        """
        Generates a name from a list of lists
        """
        try:
            random.seed(self.seed)
            generation = ""
            for list_name in list_names:
                fn = getattr(self, list_name)
                generation += fn() + " "
            
            return generation.strip()
            
        finally:
            random.seed()

    def add(self, list_name:str, words:list[str]):
        """
        Adds a custom list
        """
        if hasattr(self, list_name):
            raise ValueError(f"List name {list_name} is already in use")
        self.custom_lists[list_name] = words
        setattr(self, list_name, lambda: random.choice(self.custom_lists[list_name]))

    def abstract_artistic(self):
        return self._generate(abstract_artistic_prefixes, abstract_artistic_suffixes)
    
    def berry_dessert(self):
        return self._generate(berry_prefixes, dessert_suffixes)
    
    def personality(self):
        return random.choice(personality)
    
    def ethnicity(self):
        return random.choice(ethnicities)
    
    def actor_name_color(self):
        return random.choice(actor_name_colors)
    
    def human_name_female(self, ethnicity:str=None):
        if not ethnicity:
            ethnicity = self.ethnicity()
        
        return self._generate(human_names_female[ethnicity], [])
    
    def human_name_male(self, ethnicity:str=None):
        if not ethnicity:
            ethnicity = self.ethnicity()
        
        return self._generate(human_names_male[ethnicity], [])