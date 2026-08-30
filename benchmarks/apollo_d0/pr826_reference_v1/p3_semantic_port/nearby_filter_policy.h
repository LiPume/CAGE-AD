// Copyright 2026 CAGE-AD contributors.
// SPDX-License-Identifier: Apache-2.0
//
// Pure policy seam for the P3 semantic fixture and the Apollo overlay patch.
// This header deliberately has no Apollo or runtime dependency.

#pragma once

namespace cage_ad {
namespace p3 {

enum class NearbyFilterDomain {
  kPinnedFixed,
  kCandidateExpandedStraight,
};

template <typename LaneChangeType>
constexpr bool EligibleForNearbyFilter(
    const LaneChangeType type, const NearbyFilterDomain domain) {
  const bool pinned_fixed = type == LaneChangeType::LEFT ||
                            type == LaneChangeType::RIGHT ||
                            type == LaneChangeType::ONTO_LANE;
  return pinned_fixed ||
         (domain == NearbyFilterDomain::kCandidateExpandedStraight &&
          type == LaneChangeType::STRAIGHT);
}

constexpr bool MeetsExistingNearbyGuards(const bool overlaps_adc,
                                         const double signed_distance_m,
                                         const double distance_limit_m,
                                         const bool polygon_in_own_lane) {
  return overlaps_adc && signed_distance_m > 0.0 &&
         signed_distance_m < distance_limit_m && polygon_in_own_lane;
}

}  // namespace p3
}  // namespace cage_ad
