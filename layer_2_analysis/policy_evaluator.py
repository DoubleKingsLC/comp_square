import os
import sys
import json

# Ensure comp_square is in the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llama_index.core import VectorStoreIndex, PromptTemplate
from llama_index.llms.openai import OpenAI
from vectordb.db_client import get_vector_store
from vectordb.embedder import get_embedder
from layer_2_analysis.schemas import SegmentedPolicy, SectionEvaluation, OmissionCheck, EvaluationResult
from dotenv import load_dotenv

load_dotenv()

REGION_MAPPING = {
    "Europe": ["GDPR", "PECR"],
    "India": ["DPDP", "IT RULES"],
    "USA": ["CCPA", "COPPA", "CPRA"]
}

class PolicyEvaluator:
    def __init__(self, region: str = "Europe"):
        self.region = region
        self.allowed_regulations = REGION_MAPPING.get(self.region, ["GDPR"])
        
        # Ensure OPENAI_API_KEY is available
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is not set in the environment or .env file.")
            
        self.llm = OpenAI(model="gpt-4o", temperature=0.1)
        
        # Load the index
        self.vector_store = get_vector_store()
        self.embed_model = get_embedder()
        self.index = VectorStoreIndex.from_vector_store(
            vector_store=self.vector_store,
            embed_model=self.embed_model
        )
        # We need precise semantic matches for specific sections
        self.retriever = self.index.as_retriever(similarity_top_k=5)
        
    def _segment_policy(self, privacy_policy_text: str) -> SegmentedPolicy:
        print("Step 1: Segmenting the raw Privacy Policy into logical sections...")
        prompt_str = """
        You are a Legal Analyst.
        Please read the following raw Website Privacy Policy and segment it into logical sections.
        Divide the text where topics shift (e.g., Data Collection, User Rights, Cookies, Security Practices).
        Ensure no content is lost; every sentence must belong to a section.
        
        Privacy Policy Text:
        -----------------------
        {policy_text}
        """
        res = self.llm.structured_predict(
            SegmentedPolicy,
            PromptTemplate(prompt_str),
            policy_text=privacy_policy_text
        )
        return res

    def _evaluate_section(self, section_title: str, section_content: str) -> SectionEvaluation:
        print(f"Step 2: Retrieving laws for section [{section_title}]...")
        
        # Querying DB for matching laws
        query_str = f"In {self.region}, what do the privacy laws say about {section_title} or {section_content[:150]}?"
        nodes = self.retriever.retrieve(query_str)
        
        legal_context = ""
        for n in nodes:
            reg = n.metadata.get("regulation", "").upper()
            if any(allowed in reg for allowed in self.allowed_regulations):
                legal_context += f"\n--- [Legal Context: {reg} Article {n.metadata.get('article', 'Unknown')}] ---\n{n.get_content()}\n"
        
        if not legal_context:
            legal_context = "No specific region law found in Vector DB for this section's topic. Base judgment on general regional privacy principles."

        print(f"        Evaluating compliance of [{section_title}]...")
        
        prompt_str = """
        You are an expert privacy lawyer and security auditor.
        Evaluate the following specific Section of a Website Privacy Policy against the Ground Truth Legal Text for {region}.
        
        Website Policy Section: {section_title}
        -----------------------
        {section_content}
        
        Ground Truth Legal Text ({region}):
        -----------------------
        {legal_context}
        
        Task:
        1. Determine if this section is Compliant, Non-Compliant, or Missing Information.
        2. Identify exact breached articles from the Ground Truth Text (e.g. "GDPR Article 13") if it is non-compliant.
        3. Extract any technical security controls mentioned.
        """
        return self.llm.structured_predict(
            SectionEvaluation,
            PromptTemplate(prompt_str),
            region=self.region,
            section_title=section_title,
            section_content=section_content,
            legal_context=legal_context
        )

    def _check_omissions(self, policy_text: str) -> OmissionCheck:
        print("Step 3: Checking for mandatory policy omissions...")
        query_str = f"What mandatory disclosures must be included in a privacy policy under {self.region} privacy laws?"
        nodes = self.retriever.retrieve(query_str)
        
        legal_context = ""
        for n in nodes:
            reg = n.metadata.get("regulation", "").upper()
            if any(allowed in reg for allowed in self.allowed_regulations):
                legal_context += f"\n--- [Legal Context: {reg}] ---\n{n.get_content()}\n"

        prompt_str = """
        You are a privacy lawyer.
        Review the ENTIRE Website Privacy Policy against the mandatory disclosures required in {region}.
        Identify if the website completely forgot or omitted any legally required sections (e.g., they didn't mention children's data, or forgot data transfer disclosures).
        Provide an overall compliance score (0-100) combining the severity of these omissions.
        
        Website Privacy Policy:
        -----------------------
        {policy_text}
        
        Ground Truth Mandatory Disclosures ({region}):
        -----------------------
        {legal_context}
        """
        return self.llm.structured_predict(
            OmissionCheck,
            PromptTemplate(prompt_str),
            region=self.region,
            policy_text=policy_text,
            legal_context=legal_context
        )

    def evaluate_policy(self, privacy_policy_text: str) -> EvaluationResult:
        """
        Main orchestration loop.
        """
        # 1. Segment
        segmented_policy = self._segment_policy(privacy_policy_text)
        
        # 2. Evaluate Sections
        section_evals = []
        all_security_controls = set()
        for section in segmented_policy.sections:
            eval_res = self._evaluate_section(section.title, section.content)
            section_evals.append(eval_res)
            for control in eval_res.security_controls_mentioned:
                all_security_controls.add(control)
                
        # 3. Final Omission Check & Score
        omission_res = self._check_omissions(privacy_policy_text)
        
        # 4. Compile Target Output
        final_result = EvaluationResult(
            compliance_score=omission_res.overall_compliance_score,
            section_evaluations=section_evals,
            missing_mandatory_clauses=omission_res.missing_mandatory_clauses,
            security_controls=list(all_security_controls)
        )
        
        return final_result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy_file", help="Path to a txt file containing a website's privacy policy")
    parser.add_argument("--region", default="Europe", help="Target region to evaluate against (Europe, India, USA)")
    args = parser.parse_args()
    
    evaluator = PolicyEvaluator(region=args.region)
    
    if args.policy_file and os.path.exists(args.policy_file):
        with open(args.policy_file, 'r', encoding='utf-8') as f:
            test_policy = f.read()
    else:
        test_policy = "We collect your data indefinitely. We do not use cookies. We use basic encryption and standard firewalls to protect user data. Email us to delete your data."
        print(f"No policy file provided. Using default dummy policy.")
        
    try:
        res = evaluator.evaluate_policy(test_policy)
        print("\n=== FINAL EVALUATION RESULT ===")
        print(res.model_dump_json(indent=2))
    except Exception as e:
        print(f"Error during evaluation: {e}")
