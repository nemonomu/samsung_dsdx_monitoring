(function() {
    const metrics = ['star_rating', 'count_of_star_ratings', 'count_of_reviews', 'review_body_count'];
    const related = new Set(metrics.concat(['detailed_review_content', 'previous_review_body_count']));
    const priceColumns = ['final_sku_price', 'original_sku_price', 'savings'];
    const priceRelated = new Set(priceColumns);

    function expandGroup(fields, triggers, relatedFields, group) {
        if (!(triggers || fields).some(field => relatedFields.has(field))) return fields;
        const ordered = [];
        let inserted = false;
        fields.forEach(field => {
            if (!inserted && relatedFields.has(field)) {
                ordered.push(...group);
                inserted = true;
            }
            if (!ordered.includes(field)) ordered.push(field);
        });
        if (!inserted) ordered.push(...group);
        return [...new Set(ordered)];
    }

    window.RetailReviewColumns = {
        isRelated(field) { return related.has(field); },
        isPrice(field) { return priceRelated.has(field); },
        expand(fields, available, triggers) {
            const original = [...new Set(fields)];
            const present = new Set(available.concat(original));
            const reviewGroup = metrics.filter(field => present.has(field));
            const triggerFields = triggers || original;
            const withReviews = expandGroup(
                original, triggerFields, related, reviewGroup
            );
            return expandGroup(
                withReviews, triggerFields, priceRelated, priceColumns
            );
        }
    };
})();
