import httpx
from dotenv import load_dotenv
import os
import re
 
load_dotenv()
 
# LLM Settings
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_ENABLED = os.getenv("LLM_ENABLED", "true").lower() == "true"
GROQ_MODEL = os.getenv("GROQ_MODEL")
 
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

#build custom llm prompt for resume parsing
def build_llm_prompt(raw_text: str) -> str:
    """
    Build LLM prompt for extracting clean resume text.
    """
    return f"""
You are a resume parsing assistant.
 
Extract structured data with these sections:
PERSONAL INFORMATION
SUMMARY
SKILLS
EXPERIENCE
EDUCATION
PROJECTS
 
Rules:
- Plain text only
- No JSON
- No Markdown formatting
 
Resume Content:
----------------
{raw_text}
----------------
"""
 
#parse resume with llm
async def parse_resume_with_llm(raw_text: str) -> str:
    print("API Key:", GROQ_API_KEY)
    print("LLM Enabled:", LLM_ENABLED)
    print("GROQ Model:", GROQ_MODEL)    
    """
    Send extracted resume text to Groq LLM and return parsed text.
    """
    print("Hello in the LLm", raw_text)
 
    if not LLM_ENABLED or not GROQ_API_KEY:
        return "LLM disabled or missing API key."
   
    #sending the payload
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "You parse resumes into clean sections."},
            {"role": "user", "content": build_llm_prompt(raw_text)}
        ],
        "temperature": 0.2
    }
 
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
 
    try:
        #timeout set to 60 seconds
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{GROQ_BASE_URL}/chat/completions",
                json=payload,
                headers=headers
            )
       
        resp.raise_for_status()
        data = resp.json()  
       
        # Return parsed resume content from LLM
        return data["choices"][0]["message"]["content"]
 
    except httpx.RequestTimeout:
        print("LLM request timed out. Using fallback method for parsing.")
        # Fallback to basic text-based resume parsing if LLM times out
        return fallback_resume_parsing(raw_text)
   
    except httpx.HTTPStatusError as e:
        return f"HTTP error occurred: {str(e)}"
   
    except Exception as e:
        return f"An error occurred: {str(e)}"
 
#fallback method if llm fails
def fallback_resume_parsing(raw_text: str) -> str:
    """
    Fallback method to extract basic resume data when LLM fails or times out.
    This method uses regex and simple string matching to extract sections like
    personal information, experience, skills, etc.
    """
    name = re.search(r"([A-Z][a-z]+ [A-Z][a-z]+)", raw_text)  
    email = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", raw_text)
    phone = re.search(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", raw_text)
 
    skills = [
    # Programming Languages
    "Python", "Java", "C", "C++", "Ruby", "JavaScript", "TypeScript", "Go", "Rust", "Swift", "Kotlin", "PHP", "Perl", "Scala", "R", "Lua", "MATLAB", "Shell", "VHDL", "Objective-C",
 
    # Web Development Frameworks/Technologies
    "React", "Angular", "Vue.js", "Svelte", "Next.js", "Nuxt.js", "Ember.js", "Backbone.js", "Django", "Flask", "Spring Boot", "ASP.NET", "Express.js", "Laravel", "Ruby on Rails", "Node.js", "FastAPI",
 
    # Front-End Technologies
    "HTML", "CSS", "JavaScript", "SASS", "LESS", "Bootstrap", "Tailwind CSS", "jQuery", "Responsive Design", "AJAX", "WebAssembly",
 
    # Databases and Data Management
    "SQL", "MySQL", "PostgreSQL", "MongoDB", "SQLite", "Cassandra", "Redis", "Oracle", "MariaDB", "NoSQL", "GraphQL", "Firebase",
 
    # Cloud Platforms
    "AWS", "Azure", "Google Cloud", "Heroku", "IBM Cloud", "DigitalOcean", "Cloudflare",
 
    # DevOps and CI/CD Tools
    "Docker", "Kubernetes", "Jenkins", "Travis CI", "GitLab CI", "CircleCI", "Ansible", "Terraform", "Puppet", "Chef", "Vagrant", "CI/CD",
 
    # Version Control Systems
    "Git", "GitHub", "GitLab", "Bitbucket", "SVN", "Mercurial",
 
    # Testing and Quality Assurance
    "JUnit", "pytest", "Selenium", "Mocha", "Chai", "Jasmine", "TestNG", "Cypress", "Jest", "Karma", "Appium",
 
    # Machine Learning and Data Science
    "TensorFlow", "Keras", "PyTorch", "scikit-learn", "Pandas", "NumPy", "Matplotlib", "Seaborn", "OpenCV", "NLTK", "spaCy", "Hadoop", "Spark", "MLlib", "Tableau", "Power BI",
 
    # Software Architecture and Design Patterns
    "Microservices", "Monolithic", "Event-Driven Architecture", "CQRS", "REST", "GraphQL", "SOAP", "API Gateway", "Design Patterns", "SOLID Principles", "OOP", "TDD", "BDD", "DDD", "MVC", "MVVM",
 
    # Security
    "OAuth", "JWT", "JWT Authentication", "SSL/TLS", "Cryptography", "OWASP", "Penetration Testing", "Security Audits", "Ethical Hacking", "SOC2", "GDPR", "HIPAA",
 
    # Mobile Development
    "iOS", "Android", "Flutter", "React Native", "Swift", "Kotlin", "Xamarin", "PhoneGap", "Cordova",
 
    # Game Development
    "Unity", "Unreal Engine", "Cocos2d", "Godot", "Game Design", "VR", "AR",
 
    # Tools and IDEs
    "Visual Studio", "VSCode", "Eclipse", "IntelliJ IDEA", "PyCharm", "Xcode", "Android Studio", "WebStorm", "Sublime Text", "NetBeans", "Vim", "Emacs",
 
    # Data Visualization and BI Tools
    "Tableau", "Power BI", "QlikView", "Looker", "Google Data Studio", "D3.js", "Chart.js", "Highcharts",
 
    # Web Servers and Networking
    "Nginx", "Apache", "Tomcat", "IIS", "HAProxy", "Lighttpd", "WebSockets", "HTTP/2", "SSL/TLS", "DNS", "Load Balancing",
 
    # Other Technologies
    "Blockchain", "Cryptocurrency", "IoT", "Edge Computing", "Quantum Computing", "Docker Swarm", "Service Mesh", "FaaS", "PaaS", "SaaS"
]
    extracted_skills = [skill for skill in skills if skill in raw_text]
 
    experience = re.search(r"(.*?)(\d{4})-(\d{4})", raw_text)  
   
    parsed_text = "PERSONAL INFORMATION\n"
    parsed_text += f"- Full Name: {name.group(0) if name else 'Not found'}\n"
    parsed_text += f"- Email: {email.group(0) if email else 'Not found'}\n"
    parsed_text += f"- Phone: {phone.group(0) if phone else 'Not found'}\n\n"
   
    parsed_text += "SKILLS\n"
    parsed_text += "\n".join(extracted_skills) if extracted_skills else "No skills found\n"
   
    parsed_text += "\nEXPERIENCE\n"
    parsed_text += f"Experience: {experience.group(0) if experience else 'Not found'}\n" if experience else "No experience found\n"
   
 
    return parsed_text