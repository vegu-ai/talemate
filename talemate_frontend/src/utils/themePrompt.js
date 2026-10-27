const THEME_SCOPE = "A theme sets how Talemate looks: the colors of the surfaces, the app's controls and accents, the scene messages and the director and help chats, how message text is styled, light or dark mode, and the code editor color scheme.";

const THEME_REQUEST = "Before you change anything, ask me what look I want (the mood, light or dark, colors I like) and suggest a direction. Then read the theme, make the changes and tell me how well it reads.";

// the help agent resolves a theme by its `group__uid` id
export function buildThemePrompt(template) {
    const name = (template?.name || "").trim() || "Untitled";
    const opening = template?.locked
        ? `Help me set up a theme based on "${name}" (id ${template.group}__${template.uid}). It ships with Talemate and is locked, so build my theme as a copy of it and ask me what to call it.`
        : `Help me set up the theme "${name}" (id ${template?.group}__${template?.uid}).`;
    return `${opening}\n\n${THEME_SCOPE}\n\n${THEME_REQUEST}`;
}
