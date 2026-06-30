import base64
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage

from domain.dto.image import ImageDTO
from domain.enums import ImageType
from infra.llm_client import LLMClient
from settings import Settings

logger = logging.getLogger(__name__)


class VLMAnalyzer:
    """Анализатор изображений через Vision Language Model на базе LangChain."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm_client = LLMClient(settings)
    
    async def analyze_image(self, image: ImageDTO, image_bytes: bytes) -> ImageDTO:
        """
        Анализирует изображение и возвращает обновленный ImageDTO с описанием.
        """
        logger.info(f"Analyzing image: {image.file_path}, type: {image.image_type}")
        
        # Кодируем изображение
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        
        # Формируем промпт
        prompt = self._get_analysis_prompt(image.image_type, image.caption)
        
        try:
            # Для VLM используем прямой вызов с изображением
            # LangChain ChatOpenAI поддерживает мультимодальные сообщения
            
            messages = [
                HumanMessage(
                    content=[
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}"
                            }
                        }
                    ]
                )
            ]
            
            response = await self.llm_client.llm.ainvoke(messages)
            description = response.content
            
            # Обновляем изображение
            updated_image = image.model_copy(update={"ai_description": description})
            
            logger.info(f"Generated description: {description[:100]}...")
            return updated_image
            
        except Exception as e:
            logger.error(f"VLM analysis failed: {e}")
            return image.model_copy(update={"ai_description": f"Ошибка анализа: {str(e)}"})
    
    def _get_analysis_prompt(self, image_type: ImageType, caption: str | None) -> str:
        """Формирует промпт для VLM."""
        
        caption_text = f"\nПодпись к изображению: {caption}" if caption else ""
        
        prompts = {
            ImageType.MICROSTRUCTURE: f"""
Проанализируй микрофотографию материала и опиши:

1. **Тип микроструктуры** (зерна, волокна, дендриты, мартенсит и т.д.)
2. **Размер элементов** (примерный размер зерен/частиц)
3. **Особенности** (поры, трещины, выделения второй фазы, границы зерен)
4. **Однородность** структуры
5. **Возможные фазы** (если видны различия в контрасте/цвете)

Ответ дай структурированно, на русском языке.{caption_text}
""",
            
            ImageType.PLOT: f"""
Проанализируй график/диаграмму и опиши:

1. **Оси** (что отложено по X и Y, единицы измерения если видны)
2. **Тип зависимости** (линейная, экспоненциальная, с пиком и т.д.)
3. **Ключевые точки** (максимумы, минимумы, перегибы)
4. **Тренды** (рост, спад, плато)
5. **Количественные оценки** (если можно прочитать значения)

Если это кривая растяжения — укажи предел прочности, относительное удлинение.
Если это график свойств — укажи при каких условиях получены данные.{caption_text}
""",
            
            ImageType.SCHEME: f"""
Проанализируй схему/диаграмму и опиши:

1. **Что изображено** (установка, процесс, фазовая диаграмма)
2. **Основные компоненты** (узлы, потоки, фазы)
3. **Направления** (потоки тепла, силы, вещества)
4. **Ключевые параметры** (если указаны температуры, давления и т.д.)

Ответ дай структурированно.{caption_text}
""",
            
            ImageType.TABLE: f"""
Проанализируй таблицу и извлеки:

1. **Заголовки столбцов** (параметры)
2. **Заголовки строк** (образцы, материалы)
3. **Числовые данные** (значения с единицами)
4. **Ключевые выводы** (какие значения выделяются)

Если это таблица химического состава — перечисли элементы и их содержание.
Если это таблица свойств — перечисли свойства и значения.{caption_text}
""",
            
            ImageType.OTHER: f"""
Опиши изображение подробно и структурированно. Укажи:
- Что изображено
- Ключевые элементы
- Любые текстовые подписи или обозначения
- Возможную связь с материаловедением{caption_text}
"""
        }
        
        return prompts.get(image_type, prompts[ImageType.OTHER])