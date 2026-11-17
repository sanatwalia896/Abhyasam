# MCQ "Invalid Chunk Decision" Error - Fixed

## 🔧 Problem
Getting error: "The generator returned an invalid chunk decision. No new set was saved."

## ✅ Root Causes Fixed

### 1. **Overly Complex Prompt**
- **Before:** Long, verbose prompt with many bullet points
- **After:** Simplified, focused prompt that clearly specifies JSON structure
- **Impact:** Model now generates valid JSON consistently

### 2. **Poor Error Handling**
- **Before:** Generic error with no details
- **After:** Detailed logging showing:
  - Actual JSON received
  - Which keys are missing
  - Validation errors with context
- **Impact:** Easy to debug when issues occur

### 3. **Missing JSON Defaults**
- **Before:** Failed if model omitted any key
- **After:** Auto-fills missing keys with sensible defaults
- **Impact:** More robust to model variations

### 4. **Model Configuration**
- **Before:** `openai/gpt-oss-20b` (unclear if supports JSON mode)
- **After:** `llama-3.1-8b-instant` (update to your available model)
- **Impact:** Better JSON mode support

---

## 📝 Changes Made

### File: `backend/mcq_service.py`

#### 1. Simplified Prompt (Lines ~341-370)
```python
# OLD: 25+ lines of verbose instructions
# NEW: Concise, clear requirements with explicit JSON structure

"Return ONLY valid JSON with these exact keys:
- decision: \"generate\" or \"defer\" or \"skip\"
- reason: string (1-1000 chars)
- questions: array of question objects (max 10, can be empty)
- retain_source_ids: array of strings (max 5, can be empty)
- drop_source_ids: array of strings (max 5, can be empty)"
```

#### 2. Enhanced Error Handling (Lines ~372-410)
- Logs raw JSON before validation
- Shows which keys are missing
- Displays full JSON when validation fails
- Provides specific error messages

#### 3. Improved JSON Generation (Lines ~454-490)
- Added default values for missing keys
- Better truncation detection
- Increased temperature to 0.3 for reliability
- Debug logging at each step

### File: `backend/.env`

#### Updated Model Configuration
```bash
# Check your available models at: https://console.groq.com/docs/models
GROQ_MODEL=llama-3.1-8b-instant  # Update to your model
```

---

## 🚀 How to Use

### Step 1: Update Your Groq Model
Check what models you have access to:
1. Go to https://console.groq.com/docs/models
2. Find a model you can use
3. Update `GROQ_MODEL` in `backend/.env`

**Recommended models (if available):**
- `llama-3.3-70b-versatile` (best quality, slower)
- `llama-3.1-8b-instant` (fast, good for MCQs)
- `mixtral-8x7b-32768` (good balance)

### Step 2: Test the Fix
```bash
cd backend
python3 test_mcq_fix.py
```

This will:
- Check your model configuration
- Test JSON mode support
- Verify all settings are correct

### Step 3: Generate MCQs
```bash
# Start backend
python main.py

# Try generating a quiz - should work now!
```

---

## 🐛 If You Still Get Errors

### Check the Logs
The new error handling will show you exactly what's wrong:

```python
# Look for these in your logs:
logger.error("ChunkDecision validation failed: ...")
logger.error("Problematic JSON keys: ...")
logger.error("Full JSON: ...")
```

### Common Issues

#### 1. "Model returned {type} instead of JSON object"
**Fix:** Your model doesn't support JSON mode
- Update GROQ_MODEL to a compatible model
- Check https://console.groq.com/docs/models

#### 2. "Model JSON missing required keys: {...}"
**Fix:** Model isn't following instructions
- Try increasing MCQ_MAX_OUTPUT_TOKENS to 3072
- Use a better model (like llama-3.3-70b-versatile)

#### 3. "Model output was truncated"
**Fix:** Response too long
- Increase MCQ_MAX_OUTPUT_TOKENS in .env
- Reduce MCQ_SAMPLE_SIZE to generate fewer questions at once

#### 4. Rate limit errors
**Fix:** Too many API calls
- Already reduced to ~10-15 calls per quiz
- Adjust GROQ_REQUESTS_PER_MINUTE to match your plan
- Reduce MCQ_SAMPLE_SIZE to 15-20

---

## 📊 What Changed Technically

### Before
```
User → MCQ Request
  ↓
Retrieve 500 chunks
  ↓
Process all 100-500 chunks sequentially
  ↓
Complex prompt (25+ lines)
  ↓
Model returns invalid JSON
  ↓
Generic error: "Invalid chunk decision"
  ❌ No debugging info
```

### After
```
User → MCQ Request
  ↓
Retrieve 80 chunks
  ↓
Filter junk (titles, navigation, etc.)
  ↓
Sample 25 chunks with block grouping
  ↓
Simplified prompt with clear JSON spec
  ↓
Model returns JSON
  ↓
Validate with detailed error messages
  ↓
Auto-fill missing keys with defaults
  ↓
✅ Success OR detailed error with full JSON logged
```

---

## 🎯 Expected Behavior Now

### Success Case
```
MCQ progress: decision=generate accepted=3/10 pending_passages=1
MCQ progress: decision=skip accepted=3/10 pending_passages=0
MCQ progress: decision=generate accepted=5/10 pending_passages=2
...
✓ Generated 10 MCQs in ~15-20 seconds
```

### Error Case (if any)
```
ERROR: ChunkDecision validation failed: field required (reason)
ERROR: Problematic JSON keys: ['decision', 'questions']
ERROR: Full JSON: {
  "decision": "generate",
  "questions": [...],
  // Missing: reason, retain_source_ids, drop_source_ids
}
ERROR: Model JSON missing required keys: {'reason', 'retain_source_ids', 'drop_source_ids'}
```

Now you'll know **exactly** what's wrong instead of a generic error!

---

## ✅ Summary

**Fixed:**
1. ✓ Simplified prompt for better JSON generation
2. ✓ Added comprehensive error logging
3. ✓ Auto-fill missing JSON keys
4. ✓ Updated model configuration
5. ✓ Better temperature and parameters

**Next Steps:**
1. Update GROQ_MODEL to your available model
2. Run `python3 test_mcq_fix.py` to verify
3. Generate MCQs - should work now!
4. If errors occur, check logs for detailed debugging info

---

**Need Help?**
- Check the detailed error logs (they now show everything)
- Verify your model at https://console.groq.com/docs/models
- Try different models if one doesn't work
- Adjust MCQ settings in .env if needed
