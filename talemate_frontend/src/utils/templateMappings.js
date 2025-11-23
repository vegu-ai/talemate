/**
 * Template icon and color mappings
 * Used for displaying template types consistently across the application
 */

export function iconForTemplate(template) {
    const templateType = template.template_type;
    
    if (templateType == 'character_attribute') {
        return 'mdi-badge-account';
    } else if (templateType == 'character_detail') {
        return 'mdi-account-details';            
    } else if (templateType == 'state_reinforcement') {
        return 'mdi-image-auto-adjust';
    } else if (templateType == 'spices') {
        return 'mdi-chili-mild';
    } else if (templateType == 'writing_style') {
        return 'mdi-script-text';
    } else if (templateType == 'visual_style') {
        return 'mdi-palette';
    } else if (templateType == 'agent_persona') {
        return 'mdi-drama-masks';
    } else if (templateType == 'scene_type') {
        return 'mdi-movie-open';
    }
    return 'mdi-cube-scan';
}

export function colorForTemplate(template) {
    const templateType = template.template_type;
    
    if (templateType == 'character_attribute') {
        return 'highlight1';
    } else if (templateType == 'character_detail') {
        return 'highlight2';
    } else if (templateType == 'state_reinforcement') {
        return 'highlight3';
    } else if (templateType == 'spices') {
        return 'highlight4';
    } else if (templateType == 'writing_style') {
        return 'highlight5';
    } else if (templateType == 'visual_style') {
        return 'highlight5';
    } else if (templateType == 'agent_persona') {
        return 'persona';
    } else if (templateType == 'scene_type') {
        return 'highlight6';
    }
    return 'grey';
}

