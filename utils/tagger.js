// tagger.js - VERSION 4.0 - CONTEXT-AWARE SELECTORS (PRODUCTION)
// 
// KEY IMPROVEMENTS:
// 1. Parent context: Uses parent text to disambiguate identical elements
// 2. Position-based selectors: Uses nth-child relative to unique parents
// 3. Enhanced ElementProfile: Captures parent/sibling context for repair selectors
//
// PRESERVED FROM V3.0:
// - Shadow DOM Support
// - DOM Stabilization
// - Dropdown Option Support
// - Ground Truth data extraction

(function() {
    // ============================================
    // PHASE 1: DOM STABILIZATION
    // Wait for the page to stop changing before tagging
    // ============================================
    return new Promise((resolve) => {
        let stabilityTimer;
        
        // Failsafe: If page never settles after 3 seconds, tag anyway
        const maxWaitTimer = setTimeout(() => {
            if (observer) observer.disconnect();
            console.log('[Tagger v4.0] Failsafe triggered: Page still changing after 3s, tagging anyway');
            resolve(performTagging());
        }, 3000);

        // MutationObserver to detect DOM changes
        const observer = new MutationObserver(() => {
            clearTimeout(stabilityTimer);
            
            // Start a new stability countdown
            stabilityTimer = setTimeout(() => {
                // DOM has been stable for 300ms!
                clearTimeout(maxWaitTimer); // Cancel failsafe
                observer.disconnect();
                console.log('[Tagger v4.0] DOM stable for 300ms, starting tagging');
                resolve(performTagging());
            }, 300);
        });
        
        // Watch for changes in the entire document
        observer.observe(document.body, {
            subtree: true,
            childList: true,
            attributes: false // Don't care about attribute changes (reduces noise)
        });
        
        // Kickstart the stability timer immediately
        stabilityTimer = setTimeout(() => {
            clearTimeout(maxWaitTimer);
            observer.disconnect();
            console.log('[Tagger v4.0] Page was already stable, starting tagging');
            resolve(performTagging());
        }, 300);
    });

    // ============================================
    // MAIN TAGGING FUNCTION
    // ============================================
    function performTagging() {
        // Remove any existing tags from previous runs
        const existingTags = document.querySelectorAll('.robo-tester-tag');
        existingTags.forEach(tag => tag.remove());

        // ============================================
        // SHADOW DOM SUPPORT
        // Recursive function to find ALL elements, including inside shadow roots
        // ============================================
        function getAllElementsIncludingShadow(root) {
            const selectors = [
                'button',
                'a[href]',
                'input',
                'textarea',
                'select',
                '[role="button"]',
                '[role="link"]',
                '[onclick]',
                '[type="submit"]',
                '.cursor-pointer',
                '[style*="cursor: pointer"]',
                '[style*="cursor:pointer"]',
                'div[onclick]',
            ];
            
            // Get elements from current root
            let elements = Array.from(root.querySelectorAll(selectors.join(', ')));
            
            // Now recursively search shadow roots
            const allNodes = root.querySelectorAll('*');
            allNodes.forEach(node => {
                if (node.shadowRoot) {
                    console.log('[Tagger v4.0] Found shadow root in:', node.tagName);
                    const shadowElements = getAllElementsIncludingShadow(node.shadowRoot);
                    elements = elements.concat(shadowElements);
                }
            });
            
            return elements;
        }

        // ============================================
        // HELPER FUNCTIONS
        // ============================================
        
        // Get direct text content (excluding children)
        function getDirectText(el) {
            if (!el) return '';
            
            let text = '';
            for (let node of el.childNodes) {
                if (node.nodeType === Node.TEXT_NODE) {
                    text += node.textContent.trim();
                }
            }
            // Normalize whitespace
            return text.trim().replace(/\s+/g, ' ');
        }

        // Check if selector is unique
        function isUnique(selector) {
            try {
                const matches = document.querySelectorAll(selector);
                return matches.length === 1;
            } catch (e) {
                return false;
            }
        }

        // Check if Playwright-style selector is unique
        function isPlaywrightSelectorUnique(selector) {
            try {
                // Simple heuristic: if it contains '>>' it's a chained selector
                // We'll trust it's unique if it was constructed with parent context
                if (selector.includes('>>')) {
                    return true;
                }
                
                // For text-based selectors, try to evaluate uniqueness
                if (selector.includes(':has-text(')) {
                    const matches = document.querySelectorAll(selector.split(':has-text(')[0]);
                    return matches.length === 1;
                }
                
                return isUnique(selector);
            } catch (e) {
                return false;
            }
        }

        // Get nth-child index
        function getNthChildIndex(el) {
            let index = 1;
            let sibling = el.previousElementSibling;
            while (sibling) {
                index++;
                sibling = sibling.previousElementSibling;
            }
            return index;
        }

        // ============================================
        // NEW V4.0: EXTRACT CONTEXT (Parent/Sibling)
        // ============================================
        function extractContext(el) {
            const context = {
                parent_text: '',
                parent_tag: '',
                parent_classes: '',
                sibling_text: '',
                container_id: '',
                aria_context: ''
            };
            
            // 1. Find parent with meaningful text (search up to 5 levels)
            let parent = el.parentElement;
            let depth = 0;
            
            while (parent && depth < 5) {
                const parentText = getDirectText(parent);
                
                // Found parent with text that's different from element's text
                if (parentText && parentText.length > 0 && parentText !== getDirectText(el)) {
                    context.parent_text = parentText;
                    context.parent_tag = parent.tagName.toLowerCase();
                    context.parent_classes = parent.className;
                    
                    // Check for ID on this parent
                    if (parent.id) {
                        context.container_id = parent.id;
                    }
                    
                    break;
                }
                
                // Even without text, capture ID if present
                if (!context.container_id && parent.id) {
                    context.container_id = parent.id;
                }
                
                parent = parent.parentElement;
                depth++;
            }
            
            // 2. Find preceding sibling with text (like a label or heading)
            let sibling = el.previousElementSibling;
            let siblingDepth = 0;
            
            while (sibling && siblingDepth < 3) {
                const siblingText = getDirectText(sibling);
                if (siblingText && siblingText.length > 0) {
                    context.sibling_text = siblingText;
                    break;
                }
                sibling = sibling.previousElementSibling;
                siblingDepth++;
            }
            
            // 3. Check for ARIA context
            const ariaLabel = el.getAttribute('aria-label');
            const ariaLabelledby = el.getAttribute('aria-labelledby');
            if (ariaLabel) {
                context.aria_context = ariaLabel;
            } else if (ariaLabelledby) {
                const labelElement = document.getElementById(ariaLabelledby);
                if (labelElement) {
                    context.aria_context = getDirectText(labelElement);
                }
            }
            
            return context;
        }

        // ============================================
        // NEW V4.0: BUILD CONTEXTUAL SELECTOR
        // Uses parent text to create unique selector when element text alone isn't unique
        // ============================================
        function buildContextualSelector(el, elementText) {
            const tagName = el.tagName.toLowerCase();
            const escapedText = elementText.replace(/"/g, '\\"');
            
            // Strategy 1: Use parent text with Playwright chaining
            let parent = el.parentElement;
            let depth = 0;
            
            while (parent && depth < 5) {
                const parentText = getDirectText(parent);
                const parentTag = parent.tagName.toLowerCase();
                
                if (parentText && parentText !== elementText && parentText.length > 0) {
                    const escapedParentText = parentText.replace(/"/g, '\\"');
                    
                    // Create chained Playwright selector
                    // Format: parent:has-text("parent text") >> child:has-text("child text")
                    const contextSelector = `${parentTag}:has-text("${escapedParentText}") >> ${tagName}:has-text("${escapedText}")`;
                    
                    console.log(`[Tagger v4.0] Testing contextual selector: ${contextSelector}`);
                    
                    // This is unique by construction (parent text + child text)
                    return contextSelector;
                }
                
                // Strategy 2: Use parent with ID
                if (parent.id) {
                    const contextSelector = `#${parent.id} >> ${tagName}:has-text("${escapedText}")`;
                    console.log(`[Tagger v4.0] Using parent ID selector: ${contextSelector}`);
                    return contextSelector;
                }
                
                parent = parent.parentElement;
                depth++;
            }
            
            // Strategy 3: Position-based selector (relative to unique parent)
            return buildPositionBasedSelector(el);
        }

        // ============================================
        // NEW V4.0: BUILD POSITION-BASED SELECTOR
        // Uses nth-child relative to a unique parent
        // ============================================
        function buildPositionBasedSelector(el) {
            const path = [];
            let current = el;
            let depth = 0;
            const maxDepth = 5;

            while (current && current.nodeType === Node.ELEMENT_NODE && depth < maxDepth) {
                let selector = current.tagName.toLowerCase();
                
                // Add ID if present (makes it unique immediately)
                if (current.id && /^[a-zA-Z][\w-]*$/.test(current.id)) {
                    selector = `#${current.id}`;
                    path.unshift(selector);
                    break; // Stop here, we have uniqueness
                }
                
                // Add nth-child for specificity
                const nthIndex = getNthChildIndex(current);
                selector += `:nth-child(${nthIndex})`;
                
                path.unshift(selector);
                
                current = current.parentElement;
                depth++;
                
                // Stop at body or if we have a unique selector
                if (current === document.body || isUnique(path.join(' > '))) {
                    break;
                }
            }
            
            const finalSelector = path.join(' > ');
            console.log(`[Tagger v4.0] Position-based selector: ${finalSelector}`);
            return finalSelector;
        }

        // ============================================
        // ENHANCED V4.0: UNIVERSAL SELECTOR GENERATION
        // Now checks uniqueness and adds context when needed
        // ============================================
        function getUniversalSelector(el) {
            const tagName = el.tagName.toLowerCase();
            
            // STRATEGY 1: ID (most reliable)
            if (el.id && /^[a-zA-Z][\w-]*$/.test(el.id)) {
                const selector = `#${el.id}`;
                if (isUnique(selector)) {
                    console.log(`[Tagger v4.0] Using ID: ${selector}`);
                    return selector;
                }
            }

            // STRATEGY 2: Unique name attribute
            if (el.name) {
                const selector = `[name="${el.name}"]`;
                if (isUnique(selector)) {
                    console.log(`[Tagger v4.0] Using name: ${selector}`);
                    return selector;
                }
            }

            // STRATEGY 3: Unique data attribute
            for (let attr of el.attributes) {
                if (attr.name.startsWith('data-') && attr.value) {
                    const selector = `[${attr.name}="${attr.value}"]`;
                    if (isUnique(selector)) {
                        console.log(`[Tagger v4.0] Using data attribute: ${selector}`);
                        return selector;
                    }
                }
            }

            // STRATEGY 4: Text content (NOW WITH UNIQUENESS CHECK!)
            const text = getDirectText(el);
            if (text && text.length > 0 && text.length < 100) {
                if (tagName === 'button' || tagName === 'a') {
                    const escapedText = text.replace(/"/g, '\\"');
                    const textSelector = `${tagName}:has-text("${escapedText}")`;
                    
                    // ✅ CHECK IF UNIQUE
                    if (isUnique(textSelector)) {
                        console.log(`[Tagger v4.0] Using unique text: ${textSelector}`);
                        return textSelector;
                    } else {
                        // ✅ NOT UNIQUE: Build contextual selector
                        console.log(`[Tagger v4.0] Text not unique, building contextual selector for: "${text}"`);
                        return buildContextualSelector(el, text);
                    }
                }
            }

            // STRATEGY 5: Type attribute
            if (el.type && tagName !== 'div') {
                const selector = `${tagName}[type="${el.type}"]`;
                if (isUnique(selector)) {
                    console.log(`[Tagger v4.0] Using type: ${selector}`);
                    return selector;
                }
            }

            // STRATEGY 6: Unique ARIA attributes
            const ariaLabel = el.getAttribute('aria-label');
            if (ariaLabel) {
                const selector = `${tagName}[aria-label="${ariaLabel}"]`;
                if (isUnique(selector)) {
                    console.log(`[Tagger v4.0] Using aria-label: ${selector}`);
                    return selector;
                }
            }

            const ariaLabelledby = el.getAttribute('aria-labelledby');
            if (ariaLabelledby) {
                const selector = `${tagName}[aria-labelledby="${ariaLabelledby}"]`;
                if (isUnique(selector)) {
                    console.log(`[Tagger v4.0] Using aria-labelledby: ${selector}`);
                    return selector;
                }
            }

            // STRATEGY 7: Position-based selector (UNIVERSAL FALLBACK)
            console.log(`[Tagger v4.0] Falling back to position-based selector`);
            return buildPositionBasedSelector(el);
        }

        // ============================================
        // ENHANCED V4.0: EXTRACT ELEMENT PROFILE
        // Now includes context data for repair selectors
        // ============================================
        function extractElementProfile(el) {
            const profile = {
                selector: null,  // Will be filled by getUniversalSelector()
                text: '',
                tag: el.tagName.toLowerCase(),
                attributes: {},
                context: null  // ✅ NEW: Context data
            };
            
            // Extract text content (normalize whitespace)
            let textContent = '';
            
            // For input elements, get placeholder or value
            if (el.tagName.toLowerCase() === 'input' || el.tagName.toLowerCase() === 'textarea') {
                textContent = el.placeholder || el.value || '';
            } else {
                textContent = getDirectText(el);
            }
            
            profile.text = textContent;
            
            // Extract key attributes
            const keyAttributes = [
                'id', 'name', 'type', 'class', 'value',
                'aria-label', 'aria-labelledby', 'placeholder',
                'role', 'href', 'title', 'alt'
            ];
            
            keyAttributes.forEach(attr => {
                const value = el.getAttribute(attr);
                if (value !== null && value !== '') {
                    profile.attributes[attr] = value;
                }
            });
            
            // Also capture data-* attributes
            Array.from(el.attributes).forEach(attr => {
                if (attr.name.startsWith('data-')) {
                    profile.attributes[attr.name] = attr.value;
                }
            });
            
            // ✅ NEW V4.0: Extract context
            profile.context = extractContext(el);
            
            return profile;
        }

        // Get ALL interactive elements (including shadow DOM)
        const elements = getAllElementsIncludingShadow(document);
        console.log(`[Tagger v4.0] Found ${elements.length} total interactive elements (including shadow DOM)`);

        const elementMap = {};
        let idCounter = 1;

        // ============================================
        // STEP 1: Tag all regular interactive elements
        // ============================================
        elements.forEach(element => {
            // Check if element is visible
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            
            const isVisible = (
                rect.width > 0 &&
                rect.height > 0 &&
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                style.opacity !== '0'
            );

            if (!isVisible) return;

            // Extract complete profile with context
            const profile = extractElementProfile(element);
            
            // Generate selector (now context-aware!)
            profile.selector = getUniversalSelector(element);
            
            const elementId = idCounter++;

            // Store profile
            elementMap[elementId] = profile;

            // Create visual tag
            const tag = document.createElement('div');
            tag.className = 'robo-tester-tag';
            tag.style.cssText = `
                position: absolute;
                border: 2px solid red;
                pointer-events: none;
                z-index: 999999;
                box-sizing: border-box;
            `;

            // Position the red box over the element
            const scrollX = window.scrollX || window.pageXOffset;
            const scrollY = window.scrollY || window.pageYOffset;
            
            tag.style.left = (rect.left + scrollX) + 'px';
            tag.style.top = (rect.top + scrollY) + 'px';
            tag.style.width = rect.width + 'px';
            tag.style.height = rect.height + 'px';

            // Create number badge
            const badge = document.createElement('div');
            badge.style.cssText = `
                position: absolute;
                top: -8px;
                left: -8px;
                background: red;
                color: white;
                font-weight: bold;
                font-size: 12px;
                padding: 2px 6px;
                border-radius: 3px;
                font-family: Arial, sans-serif;
            `;
            badge.textContent = elementId;

            tag.appendChild(badge);
            document.body.appendChild(tag);
        });

        // ============================================
        // STEP 2: Handle <select> dropdown options
        // ============================================
        const selectElements = document.querySelectorAll('select');
        
        selectElements.forEach(selectElement => {
            // Check if this select is visible
            const selectRect = selectElement.getBoundingClientRect();
            const selectStyle = window.getComputedStyle(selectElement);
            
            const isSelectVisible = (
                selectRect.width > 0 &&
                selectRect.height > 0 &&
                selectStyle.display !== 'none' &&
                selectStyle.visibility !== 'hidden'
            );

            if (!isSelectVisible) return;

            // Find the select element's ID in elementMap
            let selectId = null;
            const selectSelector = getUniversalSelector(selectElement);
            
            for (let id in elementMap) {
                if (elementMap[id].selector === selectSelector) {
                    selectId = id;
                    break;
                }
            }

            if (!selectId) return;

            // Tag each <option> inside this <select>
            const options = selectElement.querySelectorAll('option');
            let validOptionIndex = 0;
            
            options.forEach((option) => {
                // Skip empty, disabled, or placeholder options
                if (!option.value || 
                    option.disabled || 
                    option.value === '' || 
                    option.value === 'select' ||
                    option.hasAttribute('disabled')) {
                    return;
                }
                
                // Create unique ID for this option (e.g., "10a", "10b")
                const optionLetter = String.fromCharCode(97 + validOptionIndex);
                const optionId = `${selectId}${optionLetter}`;
                
                // Create selector for this specific option
                const optionSelector = `${selectSelector} option[value="${option.value}"]`;
                
                // Extract option profile with context
                const optionProfile = {
                    selector: optionSelector,
                    text: option.textContent.trim().replace(/\s+/g, ' '),
                    tag: 'option',
                    attributes: {
                        value: option.value,
                        'parent-select': selectSelector
                    },
                    context: {
                        parent_text: getDirectText(selectElement.parentElement),
                        parent_tag: 'select',
                        container_id: selectElement.id || ''
                    }
                };
                
                // Store in element map
                elementMap[optionId] = optionProfile;
                
                // Create visual indicator
                const optionBadge = document.createElement('div');
                optionBadge.className = 'robo-tester-tag';
                optionBadge.style.cssText = `
                    position: absolute;
                    background: blue;
                    color: white;
                    font-weight: bold;
                    font-size: 10px;
                    padding: 2px 5px;
                    border-radius: 3px;
                    font-family: Arial, sans-serif;
                    z-index: 999999;
                    pointer-events: none;
                    white-space: nowrap;
                `;
                
                // Position next to select element
                const scrollX = window.scrollX || window.pageXOffset;
                const scrollY = window.scrollY || window.pageYOffset;
                
                optionBadge.style.left = (selectRect.right + scrollX + 5) + 'px';
                optionBadge.style.top = (selectRect.top + scrollY + (validOptionIndex * 20)) + 'px';
                
                const displayText = optionProfile.text.length > 20 ? 
                    optionProfile.text.substring(0, 20) + '...' : 
                    optionProfile.text;
                optionBadge.textContent = `${optionId}: ${displayText}`;
                
                document.body.appendChild(optionBadge);
                
                validOptionIndex++;
            });
        });

        console.log(`[Tagger v4.0] Tagged ${Object.keys(elementMap).length} total elements with context-aware selectors`);
        console.log(`[Tagger v4.0] Element map:`, elementMap);
        
        // Return the mapping as JSON string
        return JSON.stringify(elementMap);
    }
})();