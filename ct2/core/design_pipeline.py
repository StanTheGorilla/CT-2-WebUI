"""Extracted from Orchestrator — see ct2/core/orchestrator.py."""
import re

from ct2.core.formatter import (
    detect_output_type, extract_code, reassemble_html_section,
    split_html_sections, strip_think_tags,
)
from ct2.core.pipeline_util import _OUTPUT_TYPE_TO_LANG


class DesignPipelineMixin:
    _VALID_INTERACTIONS = frozenset([
        "hamburger-toggle", "smooth-scroll", "accordion", "form-validation",
        "dark-mode-toggle", "carousel", "modal", "scroll-reveal",
    ])
    @staticmethod
    def _normalize_spec(spec: dict) -> dict:
        """Normalize an Engine spec before validation.

        Strips invalid interaction names and fixes common model mistakes
        so validation doesn't reject otherwise-good specs.
        """
        valid = DesignPipelineMixin._VALID_INTERACTIONS
        for comp in spec.get("components", []):
            if "interactions" in comp:
                original = comp["interactions"]
                comp["interactions"] = [i for i in original if i in valid]
                dropped = set(original) - set(comp["interactions"])
                if dropped:
                    print(f"[design] stripped invalid interactions from {comp.get('id')}: {dropped}")
        return spec

    async def _design_pipeline(
        self, goal, goal_text: str, conversation: list[dict],
        emit, on_token, task_ovr: dict,
        skip_refinement: bool = False,
        tools: list[dict] | None = None,
        tool_executor=None,
    ) -> dict:
        """Precision-Design pipeline for new ROUTE_DESIGN generation.

        Phase 0:   Engine generates JSON spec (silent — no UI step)
        Phase 0.5: Script normalises and validates spec
        Phase 1:   Engine generates full HTML guided by the spec
        Phase 2:   Mechanical cleanup
        Phase 3:   CSS-only refinement pass
        """
        import json as _json

        # ── Phase 0: Spec generation (thinking streamed to UI) ──────
        emit("spec_generating")
        print("[design] Phase 0: generating spec")
        # Suppress content tokens during spec generation — the JSON spec
        # should not appear in the HTML preview. Only forward thinking tokens.
        def _spec_on_token(token, kind):
            if kind == "thinking":
                on_token(token, kind)
        try:
            spec = await self.engine.generate_spec(
                goal, conversation=conversation,
                task_overrides=task_ovr,
                on_token=_spec_on_token,
            )
        except (ValueError, _json.JSONDecodeError) as e:
            print(f"[design] Phase 0 failed: {e} — retrying")
            corrective = (
                f"{goal_text}\n\n"
                "Your previous output was invalid JSON. "
                "Output ONLY the JSON object with no other text."
            )
            try:
                spec = await self.engine.generate_spec(
                    corrective, conversation=conversation,
                    task_overrides=task_ovr,
                    on_token=on_token,
                )
            except (ValueError, _json.JSONDecodeError) as e2:
                print(f"[design] Phase 0 retry failed: {e2}")
                return {
                    "response": f"Design generation failed: could not produce valid spec. {e2}",
                    "thinking": "", "draft": "", "draft_thinking": "",
                    "route": "ROUTE_DESIGN", "specialist_data": None,
                    "plan": None,
                    "finish_reason": None,
                    "truncated": False,
                    "auto_continuations": 0,
                    "reflection": {
                        "goal": goal_text[:200], "complexity": "failed",
                        "lesson": "spec generation failed twice",
                        "self_score": 0.0,
                    },
                }

        # ── Phase 0.5: Normalise spec ────────────────────────────────
        spec = self._normalize_spec(spec)

        comp_ids = [c["id"] for c in spec.get("components", [])]
        if spec.get("layout_order"):
            spec["layout_order"] = [cid for cid in spec["layout_order"] if cid in comp_ids]
            for cid in comp_ids:
                if cid not in spec["layout_order"]:
                    spec["layout_order"].append(cid)
        else:
            spec["layout_order"] = comp_ids

        valid_types = {"navbar", "hero", "features", "testimonials", "cta",
                       "pricing", "contact", "footer", "gallery", "stats",
                       "team", "faq", "custom"}
        for comp in spec.get("components", []):
            if comp.get("type") not in valid_types:
                comp["type"] = "custom"

        print(f"[design] Phase 0.5: {len(spec.get('components', []))} components, "
              f"layout={spec.get('layout_order')}")
        emit("spec_validated", spec=spec)

        # ── Phase 1: Engine generates full HTML ──────────────────────
        emit("generating", editing=False)
        print("[design] Phase 1: Engine generating full page HTML")

        compact = {
            "page_title": spec.get("page_title", ""),
            "visual_style": spec.get("visual_style", ""),
            "font_pair": spec.get("font_pair", {}),
            "animation_style": spec.get("animation_style", "scroll-reveal"),
            "color_theme": spec.get("color_theme", {}),
            "layout_order": spec.get("layout_order", []),
            "components": [],
        }
        for comp in spec.get("components", []):
            c = {"id": comp["id"], "type": comp.get("type", "custom")}
            if comp.get("content"):
                c["content"] = comp["content"]
            if comp.get("style_hints"):
                c["style_hints"] = comp["style_hints"]
            if comp.get("interactions"):
                c["interactions"] = comp["interactions"]
            compact["components"].append(c)

        spec_summary = _json.dumps(compact, separators=(",", ":"))

        # Inject spec as an assistant turn — model reads it as its own prior
        # planning, not a new user instruction.
        spec_turn = {
            "role": "assistant",
            "content": (
                "I've planned the page architecture:\n\n"
                f"[PAGE SPEC]\n{spec_summary}"
            ),
        }
        gen_conversation = (conversation or []) + [
            {"role": "user", "content": goal_text},
            spec_turn,
        ]

        visual_style = spec.get("visual_style", "")
        font_pair = spec.get("font_pair", {})
        animation_style = spec.get("animation_style", "scroll-reveal")
        heading_font = font_pair.get("heading", "")
        body_font = font_pair.get("body", "")
        font_note = (
            f"Import '{heading_font}' (headings) and '{body_font}' (body) from Google Fonts. "
            if heading_font and body_font else ""
        )
        anim_note = (
            "Add CSS scroll-reveal: @keyframes fadeUp (opacity 0→1, translateY 24px→0), "
            "apply via IntersectionObserver in <script>. Stagger section entry with animation-delay. "
            if animation_style == "scroll-reveal" else
            "Add subtle fade-up entrance animations on sections. "
            if animation_style == "fade-up" else ""
        )

        gen_goal = (
            "OUTPUT ONLY HTML. Start at <!DOCTYPE html>. No text before it. No markdown fences. "
            f"Build a world-class, production-ready '{visual_style}' website following the spec above. "
            f"Include every section in layout_order. {font_note}"
            f"TYPOGRAPHY: Use the heading font for all headings (large, bold, tight letter-spacing). "
            f"Body text 17px, line-height 1.75. "
            f"HERO: Full-screen (min-h-screen), rich gradient or bold background, strong headline, clear CTA with hover effect. "
            f"SECTIONS: Generous padding (py-24 or more), never cramped. Real persuasive copy. "
            f"DEPTH: Cards with shadow-lg + hover:-translate-y-1 + hover:shadow-xl transition. "
            f"HOVER: Every button and link has smooth hover (transform + color + shadow). "
            f"{anim_note}"
            f"COLOR: Apply the color_theme cohesively — primary for CTAs, accent for highlights, background for page. "
            f"MOBILE: Mobile-first, hamburger nav on small screens. "
            f"Output only the complete HTML file — no explanations, no markdown fences."
        )

        result = await self.engine.generate(
            gen_goal, "ROUTE_DESIGN",
            conversation=gen_conversation,
            on_token=on_token,
            task_overrides=task_ovr,
            tools=tools,
            tool_executor=tool_executor,
        )
        draft = result["text"]
        draft_thinking = result.get("thinking", "")
        finish_reason = result.get("finish_reason")
        draft, draft_thinking, finish_reason, auto_continuations = await self._continue_after_length(
            draft=draft,
            draft_thinking=draft_thinking,
            finish_reason=finish_reason,
            goal_text=goal_text,
            route="ROUTE_DESIGN",
            continuation_context=gen_conversation,
            specialist_data=None,
            plan=None,
            task_ovr=task_ovr,
            emit=emit,
            on_token=on_token,
            tools=tools,
            tool_executor=tool_executor,
        )

        # ── Phase 2: Cleanup ──────────────────────────────────────
        from ct2.core.formatter import strip_think_tags, extract_code
        draft = strip_think_tags(draft)
        draft = extract_code(draft)

        # ── Phase 2.5: Validate output is actual HTML ──
        # Small models may write prose instead of HTML. Detect and retry.
        for retry_num in range(2):
            _stripped = draft.lower().strip()
            _has_html_tags = any(tag in _stripped for tag in (
                '<!doctype', '<html', '<head', '<body', '<style',
                '<div', '<section', '<header', '<main', '<footer',
                '<nav', '<h1', '<h2', '<p ', '<p>', '<a ', '<img',
            ))
            _looks_conversational = (
                _stripped.startswith(('i ', 'let ', 'here', 'sure', 'okay',
                    'certainly', 'of course', 'below', "i'll", "i'd",
                    "i've", 'i have', 'this is', 'the following',
                    'to create', 'to build', 'to make', 'first',
                    'great', 'absolutely', 'no problem',
                ))
                or len(draft.strip()) < 200
            )
            if _has_html_tags or not _looks_conversational:
                break
            if retry_num == 0:
                emit("retrying", message="Model wrote prose instead of HTML — retrying with corrective prompt…")
                corrective = (
                    "CRITICAL: Your previous response was rejected because it contained "
                    "conversational text instead of HTML.\n\n"
                    f"Build a '{visual_style}' website. Output ONLY the complete HTML "
                    "file. Start with <!DOCTYPE html>. Do NOT write ANY text before it. "
                    "No explanations. No markdown fences."
                )
                retry_result = await self.engine.generate(
                    corrective, "ROUTE_DESIGN",
                    conversation=None,
                    on_token=on_token,
                    task_overrides=task_ovr,
                    tools=tools,
                    tool_executor=tool_executor,
                )
                draft = strip_think_tags(retry_result["text"])
                draft = extract_code(draft)
                draft_thinking = (draft_thinking or "") + "\n" + retry_result.get("thinking", "")
            else:
                print("[design] Phase 2.5: retry failed, keeping output as-is")
                emit("warning", message="The model produced conversational text instead of HTML. The output may not render correctly.")

        emit("draft", text=draft, thinking=draft_thinking)

        final_response = draft
        final_thinking = draft_thinking

        # ── Phase 3: CSS-only refinement ────────────────────────────
        # Extract just the <style> block and ask the model to polish it.
        # Much safer than full-page rewrite: HTML structure is preserved,
        # the model only handles ~2-5 KB of CSS instead of the full page.
        if not skip_refinement:
            try:
                sections = split_html_sections(draft)
                css = sections.get("style", "")
                if css and len(css.strip()) > 100:
                    emit("refining")
                    refine_ovr = {**task_ovr}
                    refine_result = await self.engine.refine_css_only(
                        css, task_overrides=refine_ovr,
                    )
                    improved_css = strip_think_tags(refine_result["text"])
                    # Strip any accidental fences the model adds
                    improved_css = re.sub(r'^```\w*\s*\n?', '', improved_css.strip())
                    improved_css = re.sub(r'\n?```\s*$', '', improved_css)
                    if improved_css and len(improved_css.strip()) > 50:
                        final_response = reassemble_html_section(draft, "style", improved_css)
                        emit("polished", code=final_response)
                        print("[design] Phase 3: CSS-only refinement applied")
                    else:
                        print("[design] Phase 3: CSS refinement output empty, keeping original")
                else:
                    print("[design] Phase 3: skipping — no meaningful CSS to refine")
            except Exception as e:
                print(f"[design] Phase 3: CSS refinement failed, keeping original: {e}")

        return {
            "response": final_response,
            "thinking": final_thinking,
            "draft": draft,
            "draft_thinking": draft_thinking,
            "route": "ROUTE_DESIGN",
            "specialist_data": _json.dumps(spec),
            "plan": None,
            "finish_reason": finish_reason,
            "truncated": finish_reason == "length",
            "auto_continuations": auto_continuations,
            "reflection": None,  # Reflection handled by caller
            "spec": spec,
            "detected_lang": "html",
            "files": [],
        }

    async def _self_review(self, code: str, goal: str, route: str,
                           task_overrides: dict = None) -> dict | None:
        """Large-tier self-review: model checks its own output."""
        review_prompt = (
            f"Review this code against the original request.\n\n"
            f"REQUEST: {goal[:500]}\n\n"
            f"CODE:\n{code[:3000]}\n\n"
            f"Check for:\n"
            f"1. Does it fully address the request?\n"
            f"2. Any syntax errors or bugs?\n"
            f"3. Missing functionality?\n\n"
            f"Output ONLY a JSON object:\n"
            f'{{"pass": true, "issues": [], "fix_instructions": ""}}\n'
            f'or\n'
            f'{{"pass": false, "issues": ["issue1"], "fix_instructions": "fix this"}}'
        )
        try:
            review_ovr = {**(task_overrides or {}),
                          "temperature": 0.1, "enable_thinking": False}
            result = await self.engine.generate(
                review_prompt, route,
                task_overrides=review_ovr,
            )
            import json
            text = result["text"].strip()
            # Extract JSON from possible markdown fences
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            return json.loads(text)
        except Exception as e:
            print(f"[orch] self-review failed: {e}")
            return None

