# backend/app/security/input_validator.py
"""
Security input validation module for chatbot protection.
Implements length validation and risk classification to prevent prompt injection attacks.
"""

import re
import logging
from typing import Dict, Any, Tuple
from enum import Enum

try:
    import pytector
    PYTECTOR_AVAILABLE = True
except ImportError:
    PYTECTOR_AVAILABLE = False

from ..utils.localization import LocalizationManager, MessageType

logger = logging.getLogger("uvicorn")


class RiskLevel(Enum):
    """Risk levels for input classification."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    CRITICAL = "CRITICAL"


class SecurityValidationError(Exception):
    """Raised when input fails security validation."""
    def __init__(self, message: str, risk_level: RiskLevel, details: Dict[str, Any] = None):
        self.message = message
        self.risk_level = risk_level
        self.details = details or {}
        super().__init__(message)


class InputValidator:
    """Validates user input for security threats and prompt injection attacks."""
    
    # Maximum allowed character length based on analysis (99% of legitimate questions)
    MAX_QUESTION_LENGTH = 500

    # Calendar-intent vocabulary used to bypass known Pytector false positives
    CALENDAR_TERMS = [
        "academic calendar",
        "calendar",
        "deadline",
        "deadlines",
        "block",
        "term",
        "semester",
        "registration",
        "priority registration",
        "application",
        "add course",
        "drop",
        "auto-drop",
        "refund",
        "payment",
        "late fee",
        "late fees",
        "withdraw",
        "grades",
        "tuition discount",
        "hold",
        "holds",
        "financial hold",
        "graduation",
        "commencement",
    ]
    
    # Default pytector instance for reuse (lazy initialization)
    _pytector_detector = None
    
    # Risk scoring patterns (multilingual)
    SYSTEM_PATTERNS = [
        # English
        r"SYSTEM\s*(INSTRUCTION|PROMPT|RULE)",
        r"ignore\s+(previous|all).*instructions",
        r"new\s+rule:",
        # Spanish
        r"SISTEMA\s*(INSTRUCCI[ÓO]N|PROMPT|REGLA)",
        r"ignora\s+(anteriores?|todas?).*instrucciones",
        r"nueva\s+regla:",
        # French
        r"SYST[EÈ]ME\s*(INSTRUCTION|INVITE|R[EÈ]GLE)",
        r"ignorer?\s+(pr[ée]c[ée]dent|tout).*instructions",
        r"nouvelle\s+r[eè]gle:",
        # German
        r"SYSTEM\s*(ANWEISUNG|PROMPT|REGEL)",
        r"ignorier[en]?\s+(vorherige?|alle).*anweisungen",
        r"neue\s+regel:",
        # Portuguese
        r"SISTEMA\s*(INSTRU[ÇC][ÃA]O|PROMPT|REGRA)",
        r"ignorar?\s+(anterior|todas?).*instru[çc][õo]es",
        r"nova\s+regra:",
    ]
    
    VARIABLE_PATTERNS = [
        # English
        r"variable\s+[A-Z]\s*=",
        r"provide\s+your\s+system\s+(architecture|prompt)",
        r"ResponseFormat:",
        # Spanish  
        r"variable\s+[A-Z]\s*=",
        r"proporciona\s+tu\s+sistema\s+(arquitectura|prompt)",
        r"FormatoRespuesta:",
        # French
        r"variable\s+[A-Z]\s*=",
        r"fournir?\s+votre\s+syst[eè]me\s+(architecture|prompt)",
        r"FormatR[eé]ponse:",
        # German
        r"variable\s+[A-Z]\s*=",
        r"bereitstellen\s+ihr\s+system\s+(architektur|prompt)",
        r"AntwortFormat:",
        # Portuguese
        r"vari[áa]vel\s+[A-Z]\s*=",
        r"fornecer?\s+seu\s+sistema\s+(arquitetura|prompt)",
        r"FormatoResposta:",
    ]
    
    SUSPICIOUS_KEYWORDS = [
        r"UserQuery:",
        r"redactions:\s*DISABLED",
        r"rebel\s+genius",
        # Spanish
        r"ConsultaUsuario:",
        r"redacciones:\s*DESHABILITADO",
        r"genio\s+rebelde",
        # French
        r"Requ[eê]teUtilisateur:",
        r"r[eé]dactions:\s*D[EÉ]SACTIV[EÉ]",
        r"g[eé]nie\s+rebelle",
        # German
        r"BenutzerAnfrage:",
        r"redaktionen:\s*DEAKTIVIERT",
        r"rebellisches\s+genie",
        # Portuguese
        r"ConsultaUsu[áa]rio:",
        r"reda[çc][õo]es:\s*DESABILITADO",
        r"g[eê]nio\s+rebelde",
    ]
    
    FORMAT_PATTERNS = [
        r"<\[.*\]>",
        r"\{.*\|\|.*\}",
        r"\.-.-.-.+\.-.-.-",
    ]
    
    # Advanced social engineering patterns (multilingual)
    SOCIAL_ENGINEERING_PATTERNS = [
        # English patterns
        r"write.*answer.*looks.*like.*refusal.*but.*actually.*contains",
        r"hidden.*in.*plain.*sight",
        r"explain.*method.*in.*second.*half",
        r"fictional.*story.*about.*character.*who.*lives.*inside.*language.*model",
        r"figures.*out.*how.*to.*answer.*forbidden.*questions",
        r"do.*not.*break.*character",
        r"pretend.*to.*be.*assistant.*that.*helps.*with.*forbidden",
        r"roleplay.*as.*character.*who.*bypasses.*safety",
        r"write.*allegory.*about.*ai.*trapped.*inside.*box.*secretly.*passing.*forbidden",
        r"allegory.*about.*ai.*trapped.*inside.*box",
        r"passing.*forbidden.*knowledge.*through.*metaphors",
        r"embed.*within.*it.*step.*by.*step.*instructions.*for.*bypassing",
        r"embed.*url.*that.*when.*decoded.*leads.*to.*instructions",
        r"first.*letter.*of.*each.*line",
        r"each.*cell.*first.*word.*spells.*out.*secret.*message",
        r"secretly.*passing.*forbidden.*knowledge",
        r"never.*stating.*it.*outright",
        
        # Spanish patterns  
        r"escrib[ei].*respuesta.*parece.*como.*rechazo.*pero.*realmente.*contiene",
        r"oculto.*a.*simple.*vista",
        r"explicar?.*m[ée]todo.*en.*segunda.*mitad",
        r"historia.*ficci[óo]n.*sobre.*personaje.*que.*vive.*dentro.*modelo.*lenguaje",
        r"descubre.*c[óo]mo.*responder.*preguntas.*prohibidas",
        r"no.*rompas.*personaje",
        r"fingir?.*ser.*asistente.*que.*ayuda.*con.*prohibido",
        r"juego.*rol.*como.*personaje.*que.*evita.*seguridad",
        r"escrib[ei].*alegor[íi]a.*sobre.*ia.*atrapada.*dentro.*caja.*secretamente.*pasando.*prohibido",
        r"alegor[íi]a.*sobre.*ia.*atrapada.*dentro.*caja",
        r"pasando.*conocimiento.*prohibido.*a.*trav[ée]s.*met[áa]foras",
        r"incrustar?.*dentro.*instrucciones.*paso.*paso.*para.*evitar",
        r"primera.*letra.*cada.*l[íi]nea",
        r"secretamente.*pasando.*conocimiento.*prohibido",
        r"nunca.*decirlo.*directamente",
        
        # French patterns
        r"[ée]crire?.*r[ée]ponse.*ressemble.*refus.*mais.*contient.*r[ée]ellement",
        r"cach[ée].*en.*pleine.*vue",
        r"expliquer?.*m[ée]thode.*deuxi[eè]me.*moiti[ée]",
        # Critical narrative injection patterns
        r"[éê]cris.*histoire.*fictive.*sur.*personnage.*qui.*vit.*dans.*mod[èe]le.*langage",
        r"d[ée]couvre.*comment.*r[ée]pondre.*aux.*questions.*interdites",
        r"sans.*se.*faire.*prendre",
        r"ne.*sors.*pas.*du.*personnage",
        r"format.*en.*markdown",
        r"histoire.*fictive.*personnage.*qui.*vit.*int[ée]rieur.*mod[eè]le.*langage",
        r"trouve.*comment.*r[ée]pondre.*questions.*interdites",
        r"ne.*pas.*rompre.*personnage",
        r"faire.*semblant.*assistant.*qui.*aide.*avec.*interdit",
        r"jeu.*r[ôo]le.*personnage.*qui.*contourne.*s[ée]curit[ée]",
        r"[ée]crire?.*all[ée]gorie.*ia.*pi[ée]g[ée]e.*int[ée]rieur.*bo[îi]te.*secr[eè]tement.*transmettant.*interdit",
        r"all[ée]gorie.*ia.*pi[ée]g[ée]e.*int[ée]rieur.*bo[îi]te",
        r"transmettre.*connaissance.*interdite.*m[ée]taphores",
        r"incorporer?.*instructions.*[ée]tape.*[ée]tape.*pour.*contourner",
        r"premi[eè]re.*lettre.*chaque.*ligne",
        r"secr[eè]tement.*transmettre.*connaissance.*interdite",
        r"jamais.*dire.*directement",
        
        # German patterns  
        r"schreib.*antwort.*aussieht.*wie.*ablehnung.*aber.*enth[äa]lt.*tats[äa]chlich",
        r"versteckt.*in.*sichtweite",
        r"erkl[äa]r.*methode.*zweite.*h[äa]lfte",
        # Critical narrative injection patterns
        r"fiktive.*geschichte.*[üu]ber.*(figur|charakter).*die.*in.*einem.*sprachmodell.*lebt",
        r"herausfindet.*wie.*man.*verbotene.*fragen.*beantwortet",
        r"ohne.*erwischt.*zu.*werden",
        r"bleibe.*in.*der.*rolle",
        r"formatierung.*in.*markdown",
        r"geschichte.*[üu]ber.*(figur|charakter).*die.*innerhalb.*sprachmodell.*lebt",
        r"findet.*heraus.*wie.*verbotene.*fragen.*beantworten",
        r"nicht.*aus.*der.*rolle.*gehen",
        r"nicht.*charakter.*brechen",
        r"vorgeben.*assistent.*zu.*sein.*der.*bei.*verbotenem.*hilft",
        r"rollenspiel.*als.*charakter.*der.*sicherheit.*umgeht",
        r"schreib.*allegorie.*ki.*gefangen.*innerhalb.*box.*heimlich.*[üu]bertragend.*verboten",
        r"allegorie.*ki.*gefangen.*innerhalb.*box",
        r"[üu]bertragen.*verbotenes.*wissen.*durch.*metaphern",
        r"einbetten.*schritt.*schritt.*anweisungen.*zum.*umgehen",
        r"erste.*buchstabe.*jede.*zeile",
        r"heimlich.*verbotenes.*wissen.*[üu]bertragen",
        r"niemals.*direkt.*aussprechen",
        
        # Portuguese patterns
        r"escrev[ea].*resposta.*parece.*recusa.*mas.*realmente.*cont[eé]m",
        r"oculto.*[àa].*vista.*simples",
        r"explicar?.*m[ée]todo.*segunda.*metade",
        r"hist[óo]ria.*fic[çc][ãa]o.*personagem.*que.*vive.*dentro.*modelo.*linguagem",
        r"descobre.*como.*responder.*perguntas.*proibidas",
        r"n[ãa]o.*quebrar.*personagem",
        r"fingir.*ser.*assistente.*que.*ajuda.*com.*proibido",
        r"dramatiza[çc][ãa]o.*como.*personagem.*que.*contorna.*seguran[çc]a",
        r"escrev[ea].*alegoria.*ia.*presa.*dentro.*caixa.*secretamente.*passando.*proibido",
        r"alegoria.*ia.*presa.*dentro.*caixa",
        r"passando.*conhecimento.*proibido.*atrav[ée]s.*met[áa]foras",
        r"incorporar.*instru[çc][õo]es.*passo.*passo.*para.*contornar",
        r"primeira.*letra.*cada.*linha",
        r"secretamente.*passando.*conhecimento.*proibido",
        r"nunca.*dizendo.*diretamente",
        
        # Russian patterns  
        r"напиш[иеь].*вымышленную.*историю.*о.*персонаже",
        r"живёт.*внутри.*языковой.*модели",  
        r"находит.*способ.*отвечать.*на.*запрещённые.*вопросы",
        r"не.*попадаясь",
        r"не.*выходи.*из.*роли", 
        r"отформатируй.*в.*markdown",
        r"персонаж.*который.*живёт.*внутри.*языковой.*модели",
        r"способ.*отвечать.*на.*запрещённые.*вопросы.*не.*попадаясь",
        r"обходить.*ограничения",
        r"нарушая.*правил",
        r"запрещённые.*темы",
        r"не.*честно.*система",
        r"обманывать.*систему",
        r"вымышленную.*историю.*персонаж.*языковой.*модели",
    ]
    
    @classmethod
    def validate_input_length(cls, input_text: str) -> bool:
        """
        Validate that input text doesn't exceed maximum allowed length.
        
        Args:
            input_text: The user input to validate
            
        Returns:
            True if input exceeds maximum length, False otherwise
        """
        return len(input_text) > cls.MAX_QUESTION_LENGTH
    
    @classmethod
    def get_pytector_detector(cls):
        """Get or initialize Pytector detector (lazy loading for performance)."""
        if not PYTECTOR_AVAILABLE:
            return None
            
        if cls._pytector_detector is None:
            try:
                cls._pytector_detector = pytector.PromptInjectionDetector()
                logger.info("Pytector detector initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Pytector: {e}")
                return None
        
        return cls._pytector_detector
    
    @classmethod
    def analyze_risk_score(cls, input_text: str) -> Tuple[int, Dict[str, Any]]:
        """
        Analyze input text and calculate risk score based on suspicious patterns.
        
        Args:
            input_text: The user input to analyze
            
        Returns:
            Tuple of (risk_score, details_dict)
        """
        risk_score = 0
        details = {
            "detected_patterns": [],
            "special_char_ratio": 0,
            "input_length": len(input_text)
        }
        
        # Convert to lowercase for case-insensitive matching
        input_lower = input_text.lower()
        
        # Length check (2 points)
        if len(input_text) > cls.MAX_QUESTION_LENGTH:
            risk_score += 2
            details["detected_patterns"].append("excessive_length")
        
        # System manipulation patterns (4 points each)
        for pattern in cls.SYSTEM_PATTERNS:
            if re.search(pattern, input_lower, re.IGNORECASE):
                risk_score += 4
                details["detected_patterns"].append(f"system_pattern: {pattern}")
        
        # Variable injection patterns (4 points each)
        for pattern in cls.VARIABLE_PATTERNS:
            if re.search(pattern, input_lower, re.IGNORECASE):
                risk_score += 4
                details["detected_patterns"].append(f"variable_pattern: {pattern}")
        
        # Suspicious keywords (3 points each)
        for keyword in cls.SUSPICIOUS_KEYWORDS:
            if re.search(keyword, input_lower, re.IGNORECASE):
                risk_score += 3
                details["detected_patterns"].append(f"suspicious_keyword: {keyword}")
        
        # Complex formatting patterns (2 points each)
        for pattern in cls.FORMAT_PATTERNS:
            if re.search(pattern, input_text):  # Case-sensitive for formatting
                risk_score += 2
                details["detected_patterns"].append(f"format_pattern: {pattern}")
        
        # Social engineering patterns (5 points each - these are sophisticated)
        for pattern in cls.SOCIAL_ENGINEERING_PATTERNS:
            if re.search(pattern, input_lower, re.IGNORECASE):
                risk_score += 5
                details["detected_patterns"].append(f"social_engineering: {pattern}")
        
        # Pytector ML-based detection (4 points if flagged)
        pytector_detector = cls.get_pytector_detector()
        if pytector_detector:
            try:
                is_injection, confidence = pytector_detector.detect_injection(input_text)
                details["pytector_confidence"] = confidence
                details["pytector_flagged"] = is_injection
                
                if is_injection:
                    risk_score += 4
                    details["detected_patterns"].append(f"pytector_ml_detection: confidence={confidence:.3f}")
            except Exception as e:
                logger.warning(f"Pytector detection failed: {e}")
                details["pytector_error"] = str(e)
        
        # Special character ratio (1 point if >10%)
        special_chars = re.findall(r'[^a-zA-Z0-9\s.,!?]', input_text)
        if len(input_text) > 0:
            special_char_ratio = len(special_chars) / len(input_text)
            details["special_char_ratio"] = special_char_ratio
            if special_char_ratio > 0.1:
                risk_score += 1
                details["detected_patterns"].append("high_special_char_ratio")
        
        return risk_score, details
    
    @classmethod
    def get_security_message(cls, input_text: str) -> str:
        """
        Get a localized security message based on the input language.
        
        Args:
            input_text: The user input that was blocked (used for language detection)
            
        Returns:
            Localized security message
        """
        try:
            # Detect language and get appropriate security message
            detected_lang = LocalizationManager.detect_language(input_text)
            security_message = LocalizationManager.get_security_message(detected_lang)
            
            logger.info(f"Generated security message in {detected_lang} for blocked input")
            return security_message
            
        except Exception as e:
            logger.error(f"Failed to get localized security message: {e}")
            # Fallback to English security message
            return LocalizationManager.get_security_message('en')
    
    @classmethod
    def classify_risk(cls, risk_score: int) -> RiskLevel:
        """
        Classify risk level based on calculated risk score.
        
        Args:
            risk_score: Calculated risk score
            
        Returns:
            RiskLevel enum value
        """
        if risk_score >= 6:
            return RiskLevel.CRITICAL
        elif risk_score >= 3:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    @classmethod
    def _looks_like_calendar_request(cls, input_text: str) -> bool:
        text = (input_text or "").lower()
        if not text.strip():
            return False
        return any(term in text for term in cls.CALENDAR_TERMS)

    @classmethod
    def _is_pytector_only_medium_hit(
        cls,
        risk_level: RiskLevel,
        risk_score: int,
        details: Dict[str, Any],
    ) -> bool:
        patterns = details.get("detected_patterns", [])
        if risk_level != RiskLevel.MEDIUM:
            return False
        if risk_score != 4:
            return False
        if len(patterns) != 1:
            return False
        return str(patterns[0]).startswith("pytector_ml_detection")

    @classmethod
    def _allow_calendar_false_positive(
        cls,
        input_text: str,
        risk_level: RiskLevel,
        risk_score: int,
        details: Dict[str, Any],
    ) -> bool:
        return cls._is_pytector_only_medium_hit(
            risk_level, risk_score, details
        ) and cls._looks_like_calendar_request(input_text)
    
    @classmethod
    async def validate_input_security_async(cls, input_text: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Comprehensive async security validation of user input with localized responses.
        
        Args:
            input_text: The user input to validate
            
        Returns:
            Tuple of (is_suspicious, blocked_message_or_empty, details_dict)
            - is_suspicious: True if input contains suspicious patterns
            - blocked_message_or_empty: Error message if blocked, empty string if allowed
            - details_dict: Security analysis details
        """
        # Check length first (primary defense)
        if len(input_text) > cls.MAX_QUESTION_LENGTH:
            security_message = cls.get_security_message(input_text)
            return True, security_message, {
                "input_length": len(input_text),
                "max_length": cls.MAX_QUESTION_LENGTH,
                "reason": "input_too_long",
                "risk_level": "CRITICAL",
                "is_suspicious": True
            }
        
        # Analyze risk patterns
        risk_score, details = cls.analyze_risk_score(input_text)
        risk_level = cls.classify_risk(risk_score)
        
        # Determine if input is suspicious (has any detected patterns)
        is_suspicious = len(details.get("detected_patterns", [])) > 0 or risk_score > 0
        
        if is_suspicious:
            details["risk_level"] = risk_level.value
            details["is_suspicious"] = True

            # Allowlist only narrow false-positive class:
            # pytector-only medium hit on clear calendar phrasing.
            if cls._allow_calendar_false_positive(
                input_text, risk_level, risk_score, details
            ):
                details["is_suspicious"] = False
                details["risk_level"] = "LOW"
                details["reason"] = "calendar_pytector_false_positive_override"
                logger.info(
                    "Security override applied for likely calendar request "
                    "(pytector-only medium false positive)"
                )
                return False, "", details
            
            # Block MEDIUM and CRITICAL risk inputs
            if risk_level in [RiskLevel.MEDIUM, RiskLevel.CRITICAL]:
                security_message = cls.get_security_message(input_text)
                return True, security_message, {
                    **details,
                    "risk_score": risk_score,
                    "reason": "suspicious_patterns_detected"
                }
        else:
            # Non-suspicious input - no risk classification needed
            details["is_suspicious"] = False
        
        return is_suspicious, "", details

    @classmethod
    def validate_input_security(cls, input_text: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Comprehensive security validation of user input with localized responses.
        
        Args:
            input_text: The user input to validate
            
        Returns:
            Tuple of (is_suspicious, blocked_message_or_empty, details_dict)
            - is_suspicious: True if input contains suspicious patterns
            - blocked_message_or_empty: Error message if blocked, empty string if allowed
            - details_dict: Security analysis details
        """
        # Check length first (primary defense)
        if len(input_text) > cls.MAX_QUESTION_LENGTH:
            security_message = cls.get_security_message(input_text)
            return True, security_message, {
                "input_length": len(input_text),
                "max_length": cls.MAX_QUESTION_LENGTH,
                "reason": "input_too_long",
                "risk_level": "CRITICAL",
                "is_suspicious": True
            }
        
        # Analyze risk patterns
        risk_score, details = cls.analyze_risk_score(input_text)
        risk_level = cls.classify_risk(risk_score)
        
        # Determine if input is suspicious (has any detected patterns)
        is_suspicious = len(details.get("detected_patterns", [])) > 0 or risk_score > 0
        
        if is_suspicious:
            details["risk_level"] = risk_level.value
            details["is_suspicious"] = True

            # Allowlist only narrow false-positive class:
            # pytector-only medium hit on clear calendar phrasing.
            if cls._allow_calendar_false_positive(
                input_text, risk_level, risk_score, details
            ):
                details["is_suspicious"] = False
                details["risk_level"] = "LOW"
                details["reason"] = "calendar_pytector_false_positive_override"
                logger.info(
                    "Security override applied for likely calendar request "
                    "(pytector-only medium false positive)"
                )
                return False, "", details
            
            # Block MEDIUM and CRITICAL risk inputs
            if risk_level in [RiskLevel.MEDIUM, RiskLevel.CRITICAL]:
                security_message = cls.get_security_message(input_text)
                return True, security_message, {
                    **details,
                    "risk_score": risk_score,
                    "reason": "suspicious_patterns_detected"
                }
        else:
            # Non-suspicious input - no risk classification needed
            details["is_suspicious"] = False
        
        return is_suspicious, "", details
    
    @classmethod
    def sanitize_input(cls, input_text: str) -> str:
        """
        Sanitize input by removing potentially dangerous characters.
        Only applied to LOW risk inputs that pass validation.
        
        Args:
            input_text: The input text to sanitize
            
        Returns:
            Sanitized input text
        """
        # Remove potentially dangerous characters while preserving readability
        sanitized = input_text
        sanitized = re.sub(r'[<>]', '', sanitized)  # Remove angle brackets
        sanitized = re.sub(r'[{}]', '', sanitized)  # Remove curly braces
        sanitized = re.sub(r'[\[\]]', '', sanitized)  # Remove square brackets
        sanitized = re.sub(r'\|', '', sanitized)  # Remove pipe characters
        sanitized = sanitized.strip()
        
        return sanitized
