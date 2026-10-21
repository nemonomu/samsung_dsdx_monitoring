// Reviewed shared meanings. Never group an unknown field solely by its name.
const manualCommonDefinitions = {
  retailer_sku_name: '쇼핑몰이 상품에 표시한 이름입니다. 실제 상품명과 표시 위치는 제품군별 예시를 확인하세요.',
  sku: '제조사가 상품을 구분하는 모델명입니다. 쇼핑몰 자체 상품 번호와 구별합니다.',
  final_sku_price: '현재 선택한 상품의 판매가격입니다. 실제 금액과 확인 위치는 제품군별 예시를 확인하세요.',
  original_sku_price: '판매가격과 함께 표시된 비교가격입니다. 화면에 비교가격이 없으면 임의로 만들지 않습니다.',
  savings: '쇼핑몰에 표시된 할인 정보입니다. 금액·비율·문구 등 실제 표시 형태를 확인합니다.',
  count_of_reviews: '상품에 등록된 리뷰의 개수입니다. 별점 평가 개수와 구별합니다.',
  star_rating: '상품의 평균 별점입니다. 평점 척도와 표시값을 함께 확인합니다.',
  count_of_star_ratings: '상품에 별점을 남긴 평가의 개수입니다. 글로 작성된 리뷰 개수와 다를 수 있습니다.',
  id: '수집 행을 구분하는 관리 식별자입니다. 쇼핑몰 상품 번호와 다른 값입니다.',
  country: '프로젝트에서 사용하는 시장 코드입니다.',
  account_name: '데이터를 수집한 쇼핑몰을 구분하는 값입니다.',
  item: '쇼핑몰에서 상품을 구분하는 식별값입니다. 제조사 모델명과 구별합니다.',
  product_url: '수집한 상품의 상세 페이지 주소입니다.',
  main_rank: 'MAIN 수집 목록에서 상품이 나타난 순서입니다. 쇼핑몰의 정렬 방식도 함께 확인합니다.',
  bsr_rank: 'BSR 수집 목록에서 상품이 나타난 순서입니다. 쇼핑몰의 정렬 방식도 함께 확인합니다.',
  calendar_week: '수집 시점에 해당하는 주차를 나타내는 관리값입니다.',
  crawl_datetime: '상품 데이터를 수집한 시각입니다. 상품 출시일이나 리뷰 작성일이 아닙니다.',
};

function manualCommonKeys(datasets) {
  if (datasets.length < 2) return new Set();
  return new Set(datasets[0].fields.filter(first =>
    Object.hasOwn(manualCommonDefinitions, first.field) &&
    datasets.every(dataset => dataset.fields.some(candidate =>
      candidate.field === first.field && candidate.direct === first.direct
    ))
  ).map(field => field.field));
}

function manualFieldsForScope(datasets, category, scope) {
  const common = manualCommonKeys(datasets);
  const fields = datasets.find(dataset => dataset.category === category)?.fields || [];
  return fields.filter(field => scope === 'common' ? common.has(field.field) : !common.has(field.field));
}
