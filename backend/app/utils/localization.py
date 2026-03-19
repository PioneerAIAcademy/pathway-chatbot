# backend/app/utils/localization.py
"""
Comprehensive localization utility for multilingual chatbot support.
Provides language detection, message translation, and fallback mechanisms.
"""

import re
import logging
import json
import os
from typing import Dict, Any, Optional, Union, List
from dataclasses import dataclass
from enum import Enum

try:
    from langdetect import detect, LangDetectException
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False

logger = logging.getLogger("uvicorn")


class MessageType(Enum):
    """Types of messages that can be localized."""
    SECURITY_BLOCK = "security_block"
    SITE_INDEX = "site_index"
    ERROR = "error"
    GENERAL = "general"


@dataclass
class LanguageInfo:
    """Information about a supported language."""
    code: str  # ISO 639-1 code (e.g., 'en', 'es')
    name: str  # English name (e.g., 'English', 'Spanish')
    native_name: str  # Native name (e.g., 'English', 'Español')
    rtl: bool = False  # Right-to-left writing direction


class LocalizationManager:
    """Centralized localization management for the chatbot."""
    
    # Supported languages with comprehensive metadata
    SUPPORTED_LANGUAGES = {
        'en': LanguageInfo('en', 'English', 'English'),
        'es': LanguageInfo('es', 'Spanish', 'Español'),
        'fr': LanguageInfo('fr', 'French', 'Français'),
        'de': LanguageInfo('de', 'German', 'Deutsch'),
        'it': LanguageInfo('it', 'Italian', 'Italiano'),
        'pt': LanguageInfo('pt', 'Portuguese', 'Português'),
        'nl': LanguageInfo('nl', 'Dutch', 'Nederlands'),
        'ru': LanguageInfo('ru', 'Russian', 'Русский'),
        'zh': LanguageInfo('zh', 'Chinese', '中文'),
        'ja': LanguageInfo('ja', 'Japanese', '日本語'),
        'ko': LanguageInfo('ko', 'Korean', '한국어'),
        'ar': LanguageInfo('ar', 'Arabic', 'العربية', rtl=True),
        'he': LanguageInfo('he', 'Hebrew', 'עברית', rtl=True),
        'hi': LanguageInfo('hi', 'Hindi', 'हिन्दी'),
        'th': LanguageInfo('th', 'Thai', 'ไทย'),
        'vi': LanguageInfo('vi', 'Vietnamese', 'Tiếng Việt'),
        'tr': LanguageInfo('tr', 'Turkish', 'Türkçe'),
        'pl': LanguageInfo('pl', 'Polish', 'Polski'),
        'cs': LanguageInfo('cs', 'Czech', 'Čeština'),
        'hu': LanguageInfo('hu', 'Hungarian', 'Magyar'),
    }
    
    # Default fallback messages in multiple languages
    FALLBACK_MESSAGES = {
        MessageType.SECURITY_BLOCK: {
            'en': [
                "Sorry, I can't answer that; could you please rephrase your question and make it shorter?",
                "I'm sorry, but I can't assist with that request. If there's something else you'd like to talk about or ask, I'm here to help!",
                "Sorry, I can't comply with that request. If you want, I can help with something else or answer a different question."
            ],
            'es': [
                "Lo siento, no puedo responder eso; ¿podrías reformular tu pregunta y hacerla más corta?",
                "Lo siento, no puedo ayudar con esa solicitud. ¡Si hay algo más de lo que te gustaría hablar o preguntar, estoy aquí para ayudar!",
                "Lo siento, no puedo cumplir con esa solicitud. Si quieres, puedo ayudar con algo más o responder una pregunta diferente."
            ],
            'fr': [
                "Désolé, je ne peux pas répondre à cela ; pourriez-vous reformuler votre question et la raccourcir ?",
                "Je suis désolé, mais je ne peux pas vous aider avec cette demande. S'il y a autre chose dont vous aimeriez parler ou demander, je suis là pour vous aider !",
                "Désolé, je ne peux pas répondre à cette demande. Si vous voulez, je peux vous aider avec autre chose ou répondre à une question différente."
            ],
            'de': [
                "Entschuldigung, ich kann das nicht beantworten; könnten Sie Ihre Frage umformulieren und kürzer machen?",
                "Es tut mir leid, aber ich kann bei dieser Anfrage nicht helfen. Wenn es etwas anderes gibt, worüber Sie sprechen oder fragen möchten, bin ich hier, um zu helfen!",
                "Entschuldigung, ich kann dieser Anfrage nicht nachkommen. Wenn Sie möchten, kann ich bei etwas anderem helfen oder eine andere Frage beantworten."
            ],
            'it': [
                "Scusa, non posso rispondere a questo; potresti riformulare la tua domanda e renderla più breve?",
                "Mi dispiace, ma non posso aiutare con quella richiesta. Se c'è qualcos'altro di cui ti piacerebbe parlare o chiedere, sono qui per aiutare!",
                "Scusa, non posso soddisfare quella richiesta. Se vuoi, posso aiutare con qualcos'altro o rispondere a una domanda diversa."
            ],
            'pt': [
                "Desculpe, não posso responder isso; você poderia reformular sua pergunta e torná-la mais curta?",
                "Sinto muito, mas não posso ajudar com essa solicitação. Se há algo mais sobre o que você gostaria de falar ou perguntar, estou aqui para ajudar!",
                "Desculpe, não posso atender a essa solicitação. Se você quiser, posso ajudar com outra coisa ou responder a uma pergunta diferente."
            ],
            'ru': [
                "Извините, я не могу на это ответить; не могли бы вы переформулировать свой вопрос и сделать его короче?",
                "Извините, но я не могу помочь с этим запросом. Если есть что-то еще, о чем вы хотели бы поговорить или спросить, я здесь, чтобы помочь!",
                "Извините, я не могу выполнить этот запрос. Если хотите, я могу помочь с чем-то другим или ответить на другой вопрос."
            ],
            'zh': [
                "抱歉，我无法回答这个问题；您能重新表述您的问题并使其更简短吗？",
                "很抱歉，我无法协助处理该请求。如果您还有其他想讨论或询问的事情，我在这里为您提供帮助！",
                "抱歉，我无法满足该请求。如果您愿意，我可以帮助处理其他事情或回答不同的问题。"
            ],
            'ja': [
                "申し訳ございませんが、それにはお答えできません。質問を言い換えて短くしていただけますか？",
                "申し訳ございませんが、そのリクエストにはお手伝いできません。他に話したいことや質問したいことがありましたら、お手伝いします！",
                "申し訳ございませんが、そのリクエストにはお応えできません。よろしければ、他のことをお手伝いしたり、別の質問にお答えしたりできます。"
            ],
            'ko': [
                "죄송합니다. 그것에 대해서는 답변할 수 없습니다. 질문을 다시 표현하고 더 짧게 만들어 주실 수 있나요?",
                "죄송하지만 그 요청에 대해서는 도움을 드릴 수 없습니다. 다른 이야기하고 싶거나 물어보고 싶은 것이 있으시면 기꺼이 도와드리겠습니다!",
                "죄송합니다. 그 요청에는 응할 수 없습니다. 원하신다면 다른 것을 도와드리거나 다른 질문에 답변해 드릴 수 있습니다."
            ]
        },
        
        MessageType.SITE_INDEX: {
            'en': {
                'text': "If I was unable to give you the information you needed, try searching the Missionary Services Site Index for your topic.",
                'link_text': "Site Index"
            },
            'es': {
                'text': "Si no pude darte la información que necesitabas, intenta buscar en el Índice del Sitio de Servicios Misioneros tu tema.",
                'link_text': "Índice del Sitio"
            },
            'fr': {
                'text': "Si je n'ai pas pu vous donner les informations dont vous aviez besoin, essayez de rechercher votre sujet dans l'Index du Site des Services Missionnaires.",
                'link_text': "Index du Site"
            },
            'de': {
                'text': "Falls ich Ihnen nicht die benötigten Informationen geben konnte, versuchen Sie, Ihr Thema im Site-Index der Missionsdienste zu suchen.",
                'link_text': "Seitenindex"
            },
            'it': {
                'text': "Se non sono riuscito a darti le informazioni di cui avevi bisogno, prova a cercare il tuo argomento nell'Indice del Sito dei Servizi Missionari.",
                'link_text': "Indice del Sito"
            },
            'pt': {
                'text': "Se não consegui te dar as informações que você precisava, tente procurar seu tópico no Índice do Site de Serviços Missionários.",
                'link_text': "Índice do Site"
            },
            'ru': {
                'text': "Если я не смог предоставить вам нужную информацию, попробуйте найти вашу тему в Индексе Сайта Миссионерских Служб.",
                'link_text': "Индекс Сайта"
            },
            'zh': {
                'text': "如果我无法为您提供所需的信息，请尝试在传教士服务网站索引中搜索您的主题。",
                'link_text': "网站索引"
            },
            'ja': {
                'text': "必要な情報をお伝えできなかった場合は、宣教師サービスサイトインデックスでトピックを検索してみてください。",
                'link_text': "サイトインデックス"
            },
            'ko': {
                'text': "필요한 정보를 제공해드리지 못했다면, 선교사 서비스 사이트 색인에서 주제를 검색해보세요.",
                'link_text': "사이트 색인"
            }
        }
    }
    
    @classmethod
    def detect_language(cls, text: str, fallback: str = 'en') -> str:
        """
        Detect the language of input text using langdetect.
        
        Args:
            text: The text to analyze
            fallback: Language code to return if detection fails
            
        Returns:
            ISO 639-1 language code
        """
        if not LANGDETECT_AVAILABLE:
            logger.warning("langdetect not available, using fallback language")
            return fallback
        
        if not text or not text.strip():
            logger.info("Empty text provided, using fallback language")
            return fallback
        
        try:
            # Clean the text for better language detection
            clean_text = re.sub(r'[<>\[\]{}|]', ' ', text)
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
            # More robust requirements for reliable language detection
            word_count = len(clean_text.split())
            char_count = len(clean_text)
            
            # Need sufficient text AND words for reliable detection  
            if char_count < 25 or word_count < 5:
                # For very short text, check for obvious non-English patterns first
                foreign_patterns = [
                    r'\b(schreibe|geschichte|über|eine|figur)\b',  # German
                    r'\b(écris|histoire|sur|une)\b',  # French
                    r'\b(escribe|historia|sobre|una)\b',  # Spanish
                    r'\b(напиши|история|персонаже)\b',  # Russian
                ]
                
                has_foreign_indicators = any(re.search(pattern, clean_text, re.IGNORECASE) 
                                           for pattern in foreign_patterns)
                
                if has_foreign_indicators:
                    logger.info("Foreign language indicators detected in short text, attempting detection")
                    # Continue with detection for foreign languages
                else:
                    logger.info(f"Short English-like text ({char_count} chars, {word_count} words), using fallback")
                    return fallback
            
            # Additional English pattern check for ambiguous cases
            english_patterns = [
                r'\b(when|wen|what|wut|where|why|how|who|is|are|can|could|would|will|do|does|did)\b',
                r'\b(the|a|an|and|or|but|in|on|at|to|for|of|with|by)\b',
                r'\b(I|you|he|she|it|we|they|me|him|her|us|them)\b',
                r'\b(this|that|these|those|here|there|now|then)\b',
                r'\b(block|term|semester|registration|deadline|payment|grades?|calendar)\b',
            ]
            
            english_indicators = sum(1 for pattern in english_patterns if re.search(pattern, clean_text, re.IGNORECASE))
            
            # For short text with strong English indicators, prefer English
            if char_count < 50 and word_count < 8 and english_indicators >= 2:
                logger.info(f"Strong English indicators in short text ({english_indicators} patterns), using English")
                return 'en'
            
            detected_lang = detect(clean_text)
            
            # Normalize language code (handle variants like 'zh-cn' -> 'zh')
            normalized_lang = cls.normalize_language_code(detected_lang)
            
            # Verify we support this language
            if normalized_lang in cls.SUPPORTED_LANGUAGES:
                logger.info(f"Detected language: {normalized_lang} for text: {clean_text[:50]}...")
                return normalized_lang
            else:
                logger.warning(f"Detected unsupported language: {detected_lang}, using fallback: {fallback}")
                return fallback
            
        except LangDetectException as e:
            logger.warning(f"Language detection failed: {e}, using fallback: {fallback}")
            return fallback
        except Exception as e:
            logger.error(f"Unexpected error in language detection: {e}, using fallback: {fallback}")
            return fallback
    
    @classmethod
    def normalize_language_code(cls, lang_code: str) -> str:
        """
        Normalize language code to handle variants.
        
        Args:
            lang_code: Raw language code (e.g., 'zh-cn', 'en-US')
            
        Returns:
            Normalized language code (e.g., 'zh', 'en')
        """
        if not lang_code:
            return 'en'
        
        # Convert to lowercase and extract base language
        base_lang = lang_code.lower().split('-')[0].split('_')[0]
        
        # Handle special cases
        if base_lang in ['zh', 'chinese']:
            return 'zh'
        elif base_lang in ['ar', 'arabic']:
            return 'ar'
        elif base_lang in ['he', 'hebrew']:
            return 'he'
        
        return base_lang
    
    @classmethod
    def get_language_info(cls, lang_code: str) -> LanguageInfo:
        """
        Get comprehensive language information.
        
        Args:
            lang_code: Language code to look up
            
        Returns:
            LanguageInfo object
        """
        normalized_code = cls.normalize_language_code(lang_code)
        return cls.SUPPORTED_LANGUAGES.get(normalized_code, cls.SUPPORTED_LANGUAGES['en'])
    
    @classmethod
    def is_language_supported(cls, lang_code: str) -> bool:
        """
        Check if a language is supported.
        
        Args:
            lang_code: Language code to check
            
        Returns:
            True if supported, False otherwise
        """
        normalized_code = cls.normalize_language_code(lang_code)
        return normalized_code in cls.SUPPORTED_LANGUAGES
    
    @classmethod
    def get_message(cls, message_type: MessageType, lang_code: str, 
                   variation: Optional[int] = None, **kwargs) -> Union[str, Dict[str, str]]:
        """
        Get a localized message.
        
        Args:
            message_type: Type of message to retrieve
            lang_code: Target language code
            variation: For message types with multiple variations (like security blocks)
            **kwargs: Additional parameters for message formatting
            
        Returns:
            Localized message string or dictionary
        """
        normalized_lang = cls.normalize_language_code(lang_code)
        
        # Fall back to English if language not supported
        if normalized_lang not in cls.SUPPORTED_LANGUAGES:
            logger.warning(f"Language {lang_code} not supported, falling back to English")
            normalized_lang = 'en'
        
        # Get the message from fallback messages
        messages = cls.FALLBACK_MESSAGES.get(message_type, {})
        lang_messages = messages.get(normalized_lang, messages.get('en', {}))
        
        if isinstance(lang_messages, list):
            # Handle multiple variations (like security block messages)
            if variation is not None and 0 <= variation < len(lang_messages):
                return lang_messages[variation]
            else:
                # Return random variation if no specific variation requested
                import random
                return random.choice(lang_messages)
        elif isinstance(lang_messages, dict):
            # Handle dictionary messages (like site index)
            return lang_messages
        elif isinstance(lang_messages, str):
            # Handle simple string messages
            return lang_messages.format(**kwargs) if kwargs else lang_messages
        else:
            # Fallback to English if anything goes wrong
            english_messages = messages.get('en', {})
            if isinstance(english_messages, list):
                import random
                return random.choice(english_messages)
            return english_messages
    
    @classmethod
    def get_security_message(cls, lang_code: str, variation: Optional[int] = None) -> str:
        """
        Get a localized security block message.
        
        Args:
            lang_code: Target language code
            variation: Specific variation index (0-2), None for random
            
        Returns:
            Localized security message
        """
        return cls.get_message(MessageType.SECURITY_BLOCK, lang_code, variation)
    
    @classmethod
    def get_site_index_messages(cls, lang_code: str) -> Dict[str, str]:
        """
        Get localized Site Index messages.
        
        Args:
            lang_code: Target language code
            
        Returns:
            Dictionary with 'text' and 'link_text' keys
        """
        result = cls.get_message(MessageType.SITE_INDEX, lang_code)
        if isinstance(result, dict):
            return result
        else:
            # Fallback to English if something went wrong
            return cls.get_message(MessageType.SITE_INDEX, 'en')
    
    @classmethod
    def get_supported_languages(cls) -> List[Dict[str, str]]:
        """
        Get list of all supported languages with metadata.
        
        Returns:
            List of language dictionaries
        """
        return [
            {
                'code': info.code,
                'name': info.name,
                'native_name': info.native_name,
                'rtl': info.rtl
            }
            for info in cls.SUPPORTED_LANGUAGES.values()
        ]
    
    @classmethod 
    def load_external_translations(cls, file_path: str) -> bool:
        """
        Load translations from an external JSON file.
        This allows for easy translation updates without code changes.
        
        Args:
            file_path: Path to JSON translation file
            
        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            if not os.path.exists(file_path):
                logger.warning(f"Translation file not found: {file_path}")
                return False
            
            with open(file_path, 'r', encoding='utf-8') as f:
                external_translations = json.load(f)
            
            # Merge external translations with built-in ones
            for message_type_str, translations in external_translations.items():
                try:
                    message_type = MessageType(message_type_str)
                    if message_type not in cls.FALLBACK_MESSAGES:
                        cls.FALLBACK_MESSAGES[message_type] = {}
                    
                    cls.FALLBACK_MESSAGES[message_type].update(translations)
                    logger.info(f"Loaded external translations for {message_type_str}")
                    
                except ValueError:
                    logger.warning(f"Unknown message type in translation file: {message_type_str}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load external translations: {e}")
            return False