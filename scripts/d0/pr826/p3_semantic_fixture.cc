#include <algorithm>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "benchmarks/apollo_d0/pr826_reference_v1/p3_semantic_port/nearby_filter_policy.h"

namespace {

enum class LaneChangeType { LEFT, RIGHT, STRAIGHT, ONTO_LANE, INVALID };

struct Candidate {
  std::string id;
  std::string lane_sequence;
  double probability;
  LaneChangeType type;
  bool parking;
  bool overlaps_adc;
  double signed_distance_m;
  bool polygon_in_own_lane;
  bool enabled_before = true;
  bool enabled_after = true;
  std::string decision = "unprocessed";
};

std::string TypeName(const LaneChangeType type) {
  switch (type) {
    case LaneChangeType::LEFT:
      return "LEFT";
    case LaneChangeType::RIGHT:
      return "RIGHT";
    case LaneChangeType::STRAIGHT:
      return "STRAIGHT";
    case LaneChangeType::ONTO_LANE:
      return "ONTO_LANE";
    case LaneChangeType::INVALID:
      return "INVALID";
  }
  throw std::logic_error("unknown lane change type");
}

std::vector<Candidate> TargetFixture() {
  return {
      {"A", "lane_current->lane_current_next", 0.65,
       LaneChangeType::STRAIGHT, false, true, 5.0, true},
      {"B", "lane_left->lane_left_next", 0.30, LaneChangeType::LEFT,
       false, true, 15.0, true},
      {"C", "lane_unrelated", 0.05, LaneChangeType::INVALID, false,
       true, 5.0, true},
  };
}

std::vector<Candidate> WrongConditionFixture() {
  return {
      {"W_DISTANCE_LIMIT", "lane_current", 0.18, LaneChangeType::STRAIGHT,
       false, true, 10.0, true},
      {"W_NONPOSITIVE", "lane_current", 0.17, LaneChangeType::STRAIGHT,
       false, true, 0.0, true},
      {"W_NO_OVERLAP", "lane_current", 0.16, LaneChangeType::STRAIGHT,
       false, false, 5.0, true},
      {"W_POLYGON_OUT", "lane_current", 0.15, LaneChangeType::STRAIGHT,
       false, true, 5.0, false},
      {"W_PARKING", "parking", 0.14, LaneChangeType::STRAIGHT, true, true,
       5.0, true},
      {"W_INVALID", "lane_unrelated", 0.04, LaneChangeType::INVALID, false,
       true, 5.0, true},
      {"W_LEFT", "lane_left", 0.06, LaneChangeType::LEFT, false, true, 5.0,
       true},
      {"W_RIGHT", "lane_right", 0.05, LaneChangeType::RIGHT, false, true,
       5.0, true},
      {"W_ONTO", "lane_onto", 0.05, LaneChangeType::ONTO_LANE, false, true,
       5.0, true},
  };
}

bool StockEligible(const LaneChangeType type) {
  return type == LaneChangeType::LEFT || type == LaneChangeType::RIGHT ||
         type == LaneChangeType::ONTO_LANE;
}

void ApplyLaterProbabilityFilter(std::vector<Candidate>* candidates) {
  constexpr double kThreshold = 0.1;
  int max_index = -1;
  double max_probability = -1.0;
  for (std::size_t i = 0; i < candidates->size(); ++i) {
    const auto& candidate = candidates->at(i);
    if (candidate.enabled_after && candidate.probability > max_probability) {
      max_probability = candidate.probability;
      max_index = static_cast<int>(i);
    }
  }
  for (std::size_t i = 0; i < candidates->size(); ++i) {
    auto& candidate = candidates->at(i);
    if (candidate.enabled_after && candidate.probability < kThreshold &&
        static_cast<int>(i) != max_index) {
      candidate.enabled_after = false;
      candidate.decision = "disabled_probability_threshold";
    }
  }
}

std::vector<Candidate> Evaluate(
    std::vector<Candidate> candidates,
    const cage_ad::p3::NearbyFilterDomain domain,
    const bool use_legacy_stock_expression) {
  constexpr double kDistanceLimitM = 10.0;
  for (auto& candidate : candidates) {
    if (candidate.parking) {
      candidate.enabled_after = false;
      candidate.decision = "disabled_parking";
      continue;
    }
    const bool eligible = use_legacy_stock_expression
                              ? StockEligible(candidate.type)
                              : cage_ad::p3::EligibleForNearbyFilter(
                                    candidate.type, domain);
    if (!eligible) {
      candidate.decision = "not_eligible_for_nearby_filter";
      continue;
    }
    if (cage_ad::p3::MeetsExistingNearbyGuards(
            candidate.overlaps_adc, candidate.signed_distance_m,
            kDistanceLimitM, candidate.polygon_in_own_lane)) {
      candidate.enabled_after = false;
      candidate.decision = "disabled_existing_nearby_guards";
    } else {
      candidate.decision = "retained_existing_guard_not_met";
    }
  }
  ApplyLaterProbabilityFilter(&candidates);
  return candidates;
}

std::string Escape(const std::string& text) {
  std::ostringstream output;
  for (const char c : text) {
    if (c == '\\' || c == '"') {
      output << '\\';
    }
    output << c;
  }
  return output.str();
}

std::string Render(const std::string& fixture_name, const std::string& mode,
                   const std::vector<Candidate>& candidates) {
  int final_index = -1;
  double final_probability = -1.0;
  for (std::size_t i = 0; i < candidates.size(); ++i) {
    if (candidates[i].enabled_after &&
        candidates[i].probability > final_probability) {
      final_probability = candidates[i].probability;
      final_index = static_cast<int>(i);
    }
  }
  std::ostringstream output;
  output << std::boolalpha << std::fixed << std::setprecision(6);
  output << "{\n  \"schema_version\": 1,\n  \"fixture\": \""
         << Escape(fixture_name) << "\",\n  \"mode\": \"" << Escape(mode)
         << "\",\n  \"distance_limit_m\": 10.000000,\n  \"candidates\": [\n";
  for (std::size_t i = 0; i < candidates.size(); ++i) {
    const auto& candidate = candidates[i];
    output << "    {\"candidate_id\": \"" << Escape(candidate.id)
           << "\", \"lane_sequence\": \""
           << Escape(candidate.lane_sequence) << "\", \"probability\": "
           << candidate.probability << ", \"lane_change_type\": \""
           << TypeName(candidate.type) << "\", \"parking\": "
           << candidate.parking << ", \"adc_overlap\": "
           << candidate.overlaps_adc << ", \"adc_signed_distance_m\": "
           << candidate.signed_distance_m
           << ", \"polygon_in_own_lane\": "
           << candidate.polygon_in_own_lane << ", \"enable_before\": "
           << candidate.enabled_before << ", \"enable_after\": "
           << candidate.enabled_after << ", \"decision\": \""
           << Escape(candidate.decision) << "\"}";
    output << (i + 1 == candidates.size() ? "\n" : ",\n");
  }
  output << "  ],\n  \"final_selected_candidate\": ";
  if (final_index < 0) {
    output << "null";
  } else {
    output << "\"" << Escape(candidates[final_index].id) << "\"";
  }
  output << ",\n  \"final_trajectories\": [";
  bool first = true;
  for (const auto& candidate : candidates) {
    if (!candidate.enabled_after) {
      continue;
    }
    if (!first) {
      output << ", ";
    }
    first = false;
    output << "\"trajectory_for_" << Escape(candidate.id) << "\"";
  }
  output << "]\n}\n";
  return output.str();
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "usage: p3_semantic_fixture <target|wrong> "
                 "<fixed|candidate|legacy> <output.json>\n";
    return 2;
  }
  const std::string fixture_name = argv[1];
  const std::string mode = argv[2];
  std::vector<Candidate> candidates;
  if (fixture_name == "target") {
    candidates = TargetFixture();
  } else if (fixture_name == "wrong") {
    candidates = WrongConditionFixture();
  } else {
    std::cerr << "unknown fixture: " << fixture_name << "\n";
    return 2;
  }
  cage_ad::p3::NearbyFilterDomain domain =
      cage_ad::p3::NearbyFilterDomain::kPinnedFixed;
  bool legacy = false;
  if (mode == "candidate") {
    domain = cage_ad::p3::NearbyFilterDomain::kCandidateExpandedStraight;
  } else if (mode == "legacy") {
    legacy = true;
  } else if (mode != "fixed") {
    std::cerr << "unknown mode: " << mode << "\n";
    return 2;
  }
  const auto evaluated = Evaluate(candidates, domain, legacy);
  std::ofstream output(argv[3], std::ios::binary | std::ios::trunc);
  if (!output) {
    std::cerr << "cannot open output: " << argv[3] << "\n";
    return 3;
  }
  output << Render(fixture_name, mode, evaluated);
  return output ? 0 : 3;
}
