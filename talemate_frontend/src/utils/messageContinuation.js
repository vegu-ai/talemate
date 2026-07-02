/**
 * Splice an autocompleted continuation onto a partial message body.
 *
 * When the partial closes a dialogue quote (ends in `"`) and the
 * completion opens with a fresh quote, the two adjacent quote
 * characters would collide on naive concatenation. Drop the dangling
 * closing quote on the partial and the leading quote on the
 * completion, ensure the partial ends with a period, and join with a
 * space — yielding a clean break between the closed dialogue and the
 * next sentence. Otherwise concatenate as-is.
 *
 * Shared between CharacterMessage and NarratorMessage continue flows.
 */
export function spliceContinuation(text, completion) {
  if (text.endsWith('"') && completion.startsWith('"')) {
    const tailCompletion = completion.slice(1);
    let body = text.slice(0, -1);
    if (!body.endsWith('.')) {
      body += '.';
    }
    return body + ' ' + tailCompletion;
  }
  return text + completion;
}
