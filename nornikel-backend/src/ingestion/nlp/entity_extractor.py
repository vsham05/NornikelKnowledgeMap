import logging
from uuid import uuid4

from domain.dto.material import MaterialDTO
from domain.dto.experiment import ExperimentDTO, RegimeDTO, RegimeParameterDTO
from domain.dto.property_value import PropertyDTO
from domain.enums import MaterialClass, MaterialState
from domain.material_taxonomy import get_material_taxonomy, is_valid_material_name
from domain.ontology import get_ontology
from infra.extraction_limits import resolve_extraction_max_chars
from infra.local_models import is_high_capability_local, local_ingest_profile
from infra.llm_client import LLMClient
from infra.llm_runtime import get_effective_llm_provider, get_local_model
from ingestion.nlp.entity_normalize import (
    coerce_material_class,
    coerce_material_state,
    coerce_property_value,
    coerce_regime_type,
    split_compound_field,
)
from ingestion.nlp.extraction_language import (
    extraction_language_instruction,
    resolve_extraction_language,
)
from ingestion.nlp.extraction_validate import is_llm_template_string, pick_monolingual_label
from ingestion.nlp.text_language_normalize import normalize_extraction_payload
from settings import Settings

logger = logging.getLogger(__name__)


class EntityExtractor:
    """Извлечение сущностей из текста через LLM с использованием онтологии."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm_client = LLMClient(settings)
        self.ontology = get_ontology()
        self.material_taxonomy = get_material_taxonomy()
    
    async def extract_from_text(
        self,
        text: str,
        document_id,
        source_page: int | None = None,
        *,
        fast_mode: bool = False,
    ) -> dict:
        """
        Извлекает сущности из текста.
        
        Returns:
            {
                "materials": list[MaterialDTO],
                "experiments": list[ExperimentDTO],
                "raw_entities": dict
            }
        """
        logger.info(f"Extracting entities from text ({len(text)} chars)")
        
        max_chars = resolve_extraction_max_chars(self.settings)
        if len(text) > max_chars:
            logger.info(
                "Truncating extraction text %s → %s chars for context window",
                len(text),
                max_chars,
            )
            text = text[:max_chars] + "\n…[truncated]"
        
        # Формируем промпт с онтологией
        target_lang = resolve_extraction_language(text, self.settings.extraction_language)
        prompt = self._build_extraction_prompt(text, fast_mode=fast_mode)
        profile = local_ingest_profile(get_local_model())
        if get_effective_llm_provider() == "yandex":
            max_tokens = 12_288 if fast_mode else 16_384
        else:
            max_tokens = profile["max_output_tokens"]
            if is_high_capability_local(get_local_model()) and not fast_mode:
                max_tokens = min(profile["max_output_tokens"] + 4096, 20_480)

        try:
            raw_entities = await self.llm_client.chat_json(
                user_message=prompt,
                temperature=0.0,
                target_lang=target_lang,
                max_tokens=max_tokens,
            )
            raw_entities = await normalize_extraction_payload(
                raw_entities,
                text,
                self.llm_client,
                target_lang=target_lang,
                fast_mode=self._skip_language_normalize(fast_mode=fast_mode),
            )
            materials = self._parse_materials(
                raw_entities.get("materials", []), document_id, source_page, target_lang
            )
            experiments = self._parse_experiments(
                raw_entities.get("experiments", []), document_id, source_page, target_lang
            )
            
            logger.info(f"Extracted: {len(materials)} materials, {len(experiments)} experiments")
            
            return {
                "materials": materials,
                "experiments": experiments,
                "raw_entities": raw_entities
            }
            
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return {"materials": [], "experiments": [], "raw_entities": {}}
    
    def _use_compact_prompt(self) -> bool:
        """Shrink prompts for API models and all local tiers (more room for document text)."""
        if get_effective_llm_provider() == "yandex":
            return True
        if get_effective_llm_provider() == "local":
            return True
        return is_high_capability_local(get_local_model())

    def _skip_language_normalize(self, *, fast_mode: bool) -> bool:
        if get_effective_llm_provider() == "local":
            return True
        if get_effective_llm_provider() == "yandex":
            return True
        return fast_mode or is_high_capability_local(get_local_model())

    def _build_extraction_prompt(self, text: str, *, fast_mode: bool = False) -> str:
        """Строит промпт для извлечения с использованием онтологии."""
        compact = self._use_compact_prompt() or fast_mode
        material_taxonomy_text = self.material_taxonomy.prompt_block()

        if compact:
            properties_text = (
                "Используй canonical snake_case имена свойств "
                "(yield_strength, density, nickel_content, recovery_rate, ph, temperature и др.)."
            )
            regime_params_text = (
                "Параметры режима: temperature, duration, pressure, concentration — value + unit в JSON."
            )
        else:
            properties_list = []
            for prop_name, prop_schema in self.ontology.properties.items():
                units = ", ".join(prop_schema.expected_units) if prop_schema.expected_units else "безразмерное"
                properties_list.append(f"  - {prop_name} ({prop_schema.label}): [{units}]")
            properties_text = "\n".join(properties_list)

            regime_params_list = []
            for param_name, param_schema in self.ontology.regime_parameters.items():
                units = ", ".join(param_schema.expected_units) if param_schema.expected_units else "без единиц"
                regime_params_list.append(f"  - {param_name} ({param_schema.label}): [{units}]")
            regime_params_text = "\n".join(regime_params_list)
        
        prompt = f"""
Извлеки из научного текста сущности в формате JSON.

{material_taxonomy_text}

ИЗВЕСТНЫЕ СВОЙСТВА (используй эти canonical names):
{properties_text}

ИЗВЕСТНЫЕ ПАРАМЕТРЫ РЕЖИМОВ:
{regime_params_text}

ФОРМАТ ОТВЕТА:
{{
  "materials": [
    {{
      "name": "canonical material name",
      "aliases": ["синоним1", "синоним2"],
      "material_class": "concentrate",
      "state": "solid",
      "properties": {{
        "canonical_property_name": {{
          "value": число_или_строка_или_объект,
          "unit": "единица измерения",
          "value_min": null,
          "value_max": null,
          "conditions": {{"temperature_c": 20}},
          "source_text": "точная цитата из текста"
        }}
      }},
      "microstructure_features": ["мартенситная", "игольчатая"]
    }}
  ],
  "experiments": [
    {{
      "material_name": "название материала из списка выше",
      "regime": {{
        "regime_type": "heat_treatment|mechanical|chemical|thermomechanical|other",
        "name": "закалка",
        "parameters": {{
          "temperature": {{"value": 500, "unit": "°C"}},
          "duration": {{"value": 2, "unit": "h"}}
        }},
        "description": "дополнительное описание"
      }},
      "measured_properties": {{
        "yield_strength": {{
          "value": 850,
          "unit": "MPa",
          "source_text": "предел текучести составил 850 МПа"
        }}
      }},
      "conclusions": ["вывод1", "вывод2"]
    }}
  ]
}}

ВАЖНО:
- material_class и state: ровно одно значение из списка (не через |)
- name: конкретное вещество (никель, медь, гипс) — НЕ категории ore/concentrate/intermediate/metal/alloy
- каждый материал — отдельный объект в массиве materials
- Используй canonical names свойств из списка выше
- Если свойство не в списке, но явно упомянуто — используй snake_case
- Указывай source_text — точную цитату из текста
- Для диапазонных значений используй value_min и value_max
- Если значение зависит от условий — укажи conditions
- Если в тексте нет материалов или экспериментов — верни пустые списки
- Перечисли каждый отдельный материал и эксперимент из текста; без дубликатов
- Извлеки ВСЕ материалы и эксперименты из текста — полнота важнее краткого JSON
- Извлекай промышленную/мировую статистику (global production, annual output, market size) как properties материалов или reagents (например sulfuric/sulphuric acid) с canonical names global_production, annual_production — unit: million tonnes, Mt, t/y
- Reagents и химикаты (sulfuric acid, H2SO4, ammonia, …) — отдельные materials с properties при наличии чисел
- Блоки [TABLE]…[/TABLE] — markdown-таблицы: каждая строка = отдельная запись; не смешивай значения из разных колонок/групп; сохраняй заголовки колонок в source_text или conditions
- JSON компактный: только сущности из текста, без пояснений
- {extraction_language_instruction(resolve_extraction_language(text, self.settings.extraction_language))}
- Ключи свойств в properties/measured_properties — snake_case на английском (nickel_content, density)
- Ответь ТОЛЬКО валидным JSON, без пояснений и markdown

Текст:
{text}
"""
        return prompt
    
    def _parse_materials(
        self,
        raw_materials: list[dict],
        document_id,
        source_page: int | None,
        target_lang: str,
    ) -> list[MaterialDTO]:
        """Парсит сырые материалы в MaterialDTO."""
        materials = []
        
        for raw_mat in raw_materials:
            try:
                names = split_compound_field(raw_mat.get("name", ""))
                if not names:
                    continue

                properties = {}
                for prop_name, prop_data in raw_mat.get("properties", {}).items():
                    prop_value = coerce_property_value(
                        prop_data,
                        document_id=document_id,
                        source_page=source_page,
                    )
                    if prop_value is None:
                        continue
                    
                    schema = self.ontology.get_property_schema(prop_name)
                    category = schema.category if schema else "other"
                    
                    properties[prop_name] = PropertyDTO(
                        name=prop_name,
                        category=category,
                        value=prop_value,
                        aliases=[]
                    )

                state = coerce_material_state(raw_mat.get("state"))
                aliases = raw_mat.get("aliases", [])
                micro = raw_mat.get("microstructure_features", [])

                for idx, name in enumerate(names):
                    display = pick_monolingual_label(name, target_lang)
                    if not is_valid_material_name(display):
                        logger.debug("Skipping invalid material name (class label): %s", display)
                        continue
                    if is_llm_template_string(display):
                        logger.debug("Skipping template material name: %s", display)
                        continue
                    material = MaterialDTO(
                        id=uuid4(),
                        name=display,
                        aliases=aliases if idx == 0 else [],
                        material_class=coerce_material_class(
                            raw_mat.get("material_class") if idx == 0 else None,
                            name=name,
                            state=raw_mat.get("state"),
                        ),
                        state=state,
                        properties=properties if idx == 0 else {},
                        microstructure_features=micro if idx == 0 else [],
                        source_document_id=document_id
                    )
                    materials.append(material)
                
            except Exception as e:
                logger.warning(f"Failed to parse material: {e}, data: {raw_mat}")
        
        return materials
    
    def _parse_experiments(
        self,
        raw_experiments: list[dict],
        document_id,
        source_page: int | None,
        target_lang: str,
    ) -> list[ExperimentDTO]:
        """Парсит сырые эксперименты в ExperimentDTO."""
        experiments = []
        
        for raw_exp in raw_experiments:
            try:
                material_name = pick_monolingual_label(
                    str(raw_exp.get("material_name") or "").strip(), target_lang
                )
                if not material_name or is_llm_template_string(material_name):
                    logger.debug("Skipping experiment without valid material_name")
                    continue

                # Парсим режим
                regime_data = raw_exp.get("regime", {})
                regime_params = {}
                
                for param_name, param_data in regime_data.get("parameters", {}).items():
                    param_value = coerce_property_value(
                        param_data,
                        document_id=document_id,
                        source_page=source_page,
                    )
                    if param_value is None:
                        continue
                    
                    regime_params[param_name] = RegimeParameterDTO(
                        name=param_name,
                        value=param_value
                    )
                
                regime = RegimeDTO(
                    regime_type=coerce_regime_type(
                        regime_data.get("regime_type"),
                        name=regime_data.get("name"),
                        description=regime_data.get("description"),
                    ),
                    name=regime_data.get("name"),
                    parameters=regime_params,
                    description=regime_data.get("description")
                )
                
                # Парсим измеренные свойства
                measured_properties = {}
                for prop_name, prop_data in raw_exp.get("measured_properties", {}).items():
                    prop_value = coerce_property_value(
                        prop_data,
                        document_id=document_id,
                        source_page=source_page,
                    )
                    if prop_value is None:
                        continue
                    
                    schema = self.ontology.get_property_schema(prop_name)
                    category = schema.category if schema else "other"
                    
                    measured_properties[prop_name] = PropertyDTO(
                        name=prop_name,
                        category=category,
                        value=prop_value
                    )
                
                # Создаем эксперимент (material_id resolved in pipeline)
                experiment = ExperimentDTO(
                    id=uuid4(),
                    material_id=uuid4(),
                    regime=regime,
                    measured_properties=measured_properties,
                    conclusions=raw_exp.get("conclusions", []),
                    document_id=document_id
                )

                experiment._material_name = material_name  # type: ignore
                
                experiments.append(experiment)
                
            except Exception as e:
                logger.warning(f"Failed to parse experiment: {e}, data: {raw_exp}")
        
        return experiments