(function() {
    const metrics = ['star_rating', 'count_of_star_ratings', 'count_of_reviews', 'review_body_count'];
    const related = new Set(metrics.concat(['detailed_review_content', 'previous_review_body_count']));

    window.RetailReviewColumns = {
        isRelated(field) { return related.has(field); },
        expand(fields, available, triggers) {
            const original = [...new Set(fields)];
            if (!(triggers || original).some(field => related.has(field))) return original;
            const present = new Set(available.concat(original));
            const group = metrics.filter(field => present.has(field));
            const ordered = [];
            let inserted = false;
            original.forEach(field => {
                if (!inserted && related.has(field)) {
                    ordered.push(...group);
                    inserted = true;
                }
                if (!ordered.includes(field)) ordered.push(field);
            });
            if (!inserted) ordered.push(...group);
            return [...new Set(ordered)];
        }
    };
})();
