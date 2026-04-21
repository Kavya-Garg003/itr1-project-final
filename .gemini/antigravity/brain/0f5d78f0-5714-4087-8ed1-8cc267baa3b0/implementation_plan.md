# ITR-1 Pipeline Upgrade & Evaluation Plan

The goal is to test the RAG model and the pipeline with fake Form 16 / bank statements while upgrading the LLM backends to the best free state-of-the-art models available. We'll also dramatically improve the UI by making it look like a professional web application (including financial metrics, charts, and insights).

## User Review Required

> [!IMPORTANT]
> The plan requires installing new frontend UI libraries (like `recharts`, `lucide-react`, `framer-motion`) and running the application completely via `run_all.py`. I will also create synthetic (dummy) Form 16 and bank statement PDFs internally to safely test the app's extraction and RAG capabilities without exposing real PII.

## Proposed Changes

### Model / Backend Configuration
---

#### [MODIFY] [shared/llm_client.py](file:///e:/itr1-project-final/shared/llm_client.py)
Update the fallback provider list to prioritize top-tier free models that have excellent reasoning and math capabilities.
- Add `deepseek/deepseek-r1:free` (OpenRouter) as a strong reasoning and math alternative.
- Keep `meta-llama/llama-3.3-70b-instruct:free` (OpenRouter) and `llama-3.3-70b-versatile` (Groq).
- Add `qwen/qwen-2.5-vl-72b-instruct:free` as another Vision option if needed.

### Frontend UI & Metrics Improvements
---

#### [MODIFY] [frontend/package.json](file:///e:/itr1-project-final/frontend/package.json)
Install new dependencies for charts and icons: `recharts`, `lucide-react`, `framer-motion`, `clsx`, `tailwind-merge`.

#### [MODIFY] [frontend/src/app/form/page.tsx](file:///e:/itr1-project-final/frontend/src/app/form/page.tsx)
- Redesign the form viewer into a professional Finance Dashboard.
- **Charts:** Add a Bar Chart comparing Old vs New tax regimes visually.
- **Metrics Breakdown:** Add a Donut Chart or summary cards for `Gross Income` vs `Total Deductions` vs `Tax Paid`.
- **Insights Panel:** Add a section that gives personalized tax tips (e.g. "If you invest ₹X more in 80C, you save ₹Y in tax").

#### [MODIFY] [frontend/src/app/upload/page.tsx](file:///e:/itr1-project-final/frontend/src/app/upload/page.tsx)
- Improve the landing page to feature a modern, gradient-rich, glossy hero section.
- Upgrade the file dropper with modern animations and drag-and-drop feedback.

#### [MODIFY] [frontend/src/app/chat/page.tsx](file:///e:/itr1-project-final/frontend/src/app/chat/page.tsx)
- Redesign chat UI to feel like a premium conversational agent, with neat citation rendering.

### Testing & Evaluation
---

#### [NEW] [tests/generate_fake_docs.py](file:///e:/itr1-project-final/tests/generate_fake_docs.py)
A script to generate a fake "Form 16" and "Bank Statement" PDF/Image populated with dummy, realistic numbers (e.g. ₹12,00,000 salary, ₹30,000 savings interest, ₹1,50,000 80C) using `reportlab` or similar, to be used in our tests.

#### [NEW] Browser Testing using Subagent
We will map out the complete journey using the `browser_subagent`:
1. Start the services.
2. The subagent will open `http://localhost:3000`.
3. Upload our generated dummy Form 16 and Bank Statement.
4. View the structured extraction dashboard, verifying no hallucinations.
5. Ask specific RAG queries in the Chat app to ensure the AI responds faithfully to our dummy document context and the tax rules base.

## Open Questions

> [!TIP]
> Does this sound like the level of professional polish you're aiming for? Are there any specific new text/vision free-tier models you wanted to include that weren't mentioned above?

## Verification Plan

### Automated/Manual Testing
- Creating dummy documents and manually passing them through the UI via our `browser_subagent` ensures pure, realistic testing of the entire user journey.
- The subagent's video recording will provide proof of the UI updates and flawless chat context verification.
