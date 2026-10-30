// Detector-hit truth capture. Never infer interaction identity from position
// or from DDG4's final (potentially reduced/reparented) particle map.
#include <DDG4/EventParameters.h>
#include <DDG4/Factories.h>
#include <DDG4/Geant4Data.h>
#include <DDG4/Geant4HitCollection.h>
#include <DDG4/Geant4OutputAction.h>
#include <DDG4/Geant4Primary.h>
#include <DDG4/Geant4SteppingAction.h>
#include <DDG4/Geant4TrackingAction.h>
#include <G4Event.hh>
#include <G4SDManager.hh>
#include <G4Step.hh>
#include <G4Track.hh>
#include <G4VProcess.hh>
#include <TFile.h>
#include <TTree.h>
#include <array>
#include <cstdint>
#include <filesystem>
#include <map>
#include <memory>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

using namespace dd4hep::sim;
namespace dd4hep::sim {
class ColliderMLTruthCapture : public Geant4OutputAction {
  struct Track {
    int id = 0, input = -1, parent = -1, vertex = 0, pdg = 0;
    std::array<double,4> p{}, position{};
  };
  struct Vertex {
    int id = 0, parent = -1;
    uint16_t process = 0;
    std::array<double,4> position{};
  };
public:
  ColliderMLTruthCapture(Geant4Context* c, const std::string& name) : Geant4OutputAction(c, name) {
    c->trackingAction().callAtBegin(this, &ColliderMLTruthCapture::trackBegin);
    c->steppingAction().call(this, &ColliderMLTruthCapture::step);
  }

  void begin(const G4Event* event) override {
    // DDG4 can invoke the output action twice. Initialize each event only once.
    if (m_file && m_event == event->GetEventID()) return;
    if (m_file) throw std::runtime_error("Previous live capture was not committed");
    m_event = event->GetEventID();
    m_done = false;
    m_nextVertex = 0;
    m_tracks.clear(); m_vertices.clear(); m_pending.clear(); m_g4.clear(); m_kept.clear();
    const auto path = m_output + "/capture_" + std::to_string(m_event) + ".root";
    if (std::filesystem::exists(path)) throw std::runtime_error("Truth capture would overwrite " + path);
    m_file.reset(TFile::Open(path.c_str(), "CREATE"));
    if (!m_file || m_file->IsZombie()) throw std::runtime_error("Cannot create " + path);
    m_file->SetCompressionLevel(4);
  }

  void trackBegin(const G4Track* track) {
    if (!m_file) throw std::runtime_error("Tracking started before live capture initialization");
    const int g4id = track->GetTrackID();
    if (m_g4.count(g4id)) return; // Resume a suspended track, do not duplicate it.
    int id;
    auto pending = m_pending.find(track);
    if (pending != m_pending.end()) {
      id = pending->second; m_pending.erase(pending);
    } else {
      if (track->GetParentID() != 0)
        throw std::runtime_error("Secondary has no captured creation step");
      const int vertex = ++m_nextVertex;
      m_vertices.emplace(vertex, Vertex{vertex, -1, 0, position(track)});
      id = addTrack(track, -1, vertex);
    }
    auto& row = m_tracks.at(id);
    // Native primary associations also identify generator-specified decay daughters.
    if (auto* primary = track->GetDynamicParticle()->GetPrimaryParticle()) {
      auto* particle = context()->event().extension<Geant4PrimaryMap>()->get(primary);
      if (!particle) throw std::runtime_error("Unresolved generator primary association");
      row.input = particle->id;
    }
    m_g4.emplace(g4id, id);
  }

  void step(const G4Step* step, G4SteppingManager*) {
    const auto* secondaries = step->GetSecondaryInCurrentStep();
    if (secondaries->empty()) return;
    const int parent = m_g4.at(step->GetTrack()->GetTrackID());
    const int vertex = ++m_nextVertex;
    const auto* post = step->GetPostStepPoint();
    const auto& pos = post->GetPosition();
    const std::array<double,4> creation = {pos.x()/CLHEP::mm, pos.y()/CLHEP::mm,
                                         pos.z()/CLHEP::mm, post->GetGlobalTime()/CLHEP::ns};
    for (const auto* secondary : *secondaries) {
      const auto creator = secondary->GetCreatorProcess() ? subtype(secondary->GetCreatorProcess()) : 0;
      auto [v, inserted] = m_vertices.emplace(vertex, Vertex{vertex, parent, static_cast<uint16_t>(creator), creation});
      if (!inserted && v->second.process != creator) v->second.process = 0;
      const int child = addTrack(secondary, parent, vertex);
      if (!m_pending.emplace(secondary, child).second)
        throw std::runtime_error("Secondary pointer was already awaiting tracking");
    }
  }

  void end(const G4Event* event) override {
    if (m_done && m_event == event->GetEventID()) return;
    Geant4OutputAction::end(event);
    m_done = true;
  }

  void saveEvent(OutputContext<G4Event>& event) override {
    TFile::TContext directory(m_file.get());
    int simulation_id = event.context->GetEventID(), capture_version = 3;
    auto* parameters = context()->event().extension<EventParameters>(false);
    int source_id = parameters ? parameters->eventNumber() : simulation_id;
    TTree header("Event", "Detector-hit ancestry capture identity");
    header.Branch("simulation_id", &simulation_id); header.Branch("source_id", &source_id);
    header.Branch("capture_version", &capture_version); header.Fill(); header.Write();
    auto* input = context()->event().extension<Geant4PrimaryInteraction>();
    TTree inputs("Inputs", "Imported generator identities in DDG4 reader order");
    int input_id, pdg, status;
    inputs.Branch("input_id", &input_id); inputs.Branch("pdg_id", &pdg); inputs.Branch("status", &status);
    for (const auto& [id,p] : input->particles) {
      input_id=id;pdg=p->pdgID;status=p->genStatus;inputs.Fill();
    }
    inputs.Write();
    m_hits = new TTree("Hits", "Sensitive-detector contributions with original live track ownership");
    m_hits->Branch("track_id", &m_id); m_hits->Branch("channel", &m_channel);
    m_hits->Branch("collection_id", &m_collection); m_hits->Branch("cell_id", &m_cell);
    m_hits->Branch("energy", &m_deposit);
  }

  void saveCollection(OutputContext<G4Event>&, G4VHitsCollection* collection) override {
    auto* hits = dynamic_cast<Geant4HitCollection*>(collection);
    if (!hits) throw std::runtime_error("Unsupported truth hit collection");
    int collection_id = G4SDManager::GetSDMpointer()->GetCollectionID(collection);
    if (collection_id < 0) throw std::runtime_error("Unregistered hit collection");
    m_collection = collection_id;
    bool tracker = hits->type().type() == typeid(Geant4Tracker::Hit);
    bool calo = hits->type().type() == typeid(Geant4Calorimeter::Hit);
    if (!tracker && !calo) throw std::runtime_error("Unsupported truth hit type");
    m_channel = tracker ? 0 : 2;
    auto fill = [&](int original_track, double energy) {
      auto owner = m_g4.find(original_track);
      if (owner == m_g4.end()) throw std::runtime_error("Hit owner missing from live capture");
      m_id=owner->second; m_deposit=energy/CLHEP::GeV; m_hits->Fill();
      // Preserve original ownership and every ancestor, without hitless sibling branches.
      for (int id=m_id; id!=-1 && m_kept.insert(id).second; id=m_tracks.at(id).parent) {}
    };
    for (unsigned i=0;i<collection->GetSize();++i) {
      if (tracker) {
        const Geant4Tracker::Hit* hit=hits->hit(i);
        m_cell=static_cast<uint64_t>(hit->cellID); fill(hit->truth.trackID,hit->energyDeposit);
      } else {
        const Geant4Calorimeter::Hit* hit=hits->hit(i);
        m_cell=static_cast<uint64_t>(hit->cellID);
        for (const auto& contribution:hit->truth) fill(contribution.trackID,contribution.deposit);
      }
    }
  }
  void commit(OutputContext<G4Event>&) override {
    TFile::TContext directory(m_file.get());
    Track row;
    TTree tracks("Tracks", "Detector-hit contributors and ancestors at creation");
    tracks.Branch("id", &row.id); tracks.Branch("input_id", &row.input);
    tracks.Branch("parent_id", &row.parent); tracks.Branch("production_vertex_id", &row.vertex);
    tracks.Branch("pdg_id", &row.pdg); p4Branches(&tracks,"",row.p);
    tracks.Branch("x", &row.position[0]); tracks.Branch("y", &row.position[1]);
    tracks.Branch("z", &row.position[2]); tracks.Branch("time", &row.position[3]);
    std::unordered_set<int> keptVertices;
    for (const auto& [id,p] : m_tracks) {
      if (!m_kept.count(id)) continue;
      row=p; tracks.Fill(); keptVertices.insert(p.vertex);
    }
    tracks.Write();
    tracks.SetDirectory(nullptr);
    Vertex v;
    TTree vertices("Vertices", "Actual creation steps and source injection vertices");
    vertices.Branch("id", &v.id); vertices.Branch("parent_track_id", &v.parent);
    vertices.Branch("process_subtype", &v.process);
    vertices.Branch("x", &v.position[0]); vertices.Branch("y", &v.position[1]);
    vertices.Branch("z", &v.position[2]); vertices.Branch("time", &v.position[3]);
    for (const auto& [id,value] : m_vertices) {
      if (!keptVertices.count(id)) continue;
      v=value; vertices.Fill();
    }
    vertices.Write();
    vertices.SetDirectory(nullptr);
    m_file->Write();m_file->Close();m_file.reset();
    m_hits=nullptr;
  }
private:
  static uint16_t subtype(const G4VProcess* p) {
    const int value=p->GetProcessSubType();
    if(value<0||value>65535)throw std::runtime_error("Invalid process subtype");
    return static_cast<uint16_t>(value);
  }
  static std::array<double,4> p4(const G4ThreeVector& p,double e) {
    return {p.x()/CLHEP::GeV,p.y()/CLHEP::GeV,p.z()/CLHEP::GeV,e/CLHEP::GeV};
  }
  static std::array<double,4> momentum(const G4Track* t) {return p4(t->GetMomentum(),t->GetTotalEnergy());}
  static std::array<double,4> position(const G4Track* t) {
    const auto& p=t->GetPosition();
    return {p.x()/CLHEP::mm,p.y()/CLHEP::mm,p.z()/CLHEP::mm,t->GetGlobalTime()/CLHEP::ns};
  }
  static void p4Branches(TTree* tree,const std::string& prefix,std::array<double,4>& p) {
    const char* names[]={"px","py","pz","energy"};
    for(int i=0;i<4;++i)tree->Branch((prefix+names[i]).c_str(),&p[i]);
  }
  int addTrack(const G4Track* t,int parent,int vertex) {
    const int id=static_cast<int>(m_tracks.size()+1);
    m_tracks.emplace(id,Track{id,-1,parent,vertex,t->GetDefinition()->GetPDGEncoding(),momentum(t),position(t)});
    if (auto* primary = t->GetDynamicParticle()->GetPrimaryParticle()) {
      auto* particle = context()->event().extension<Geant4PrimaryMap>()->get(primary);
      if (!particle) throw std::runtime_error("Unresolved generator association at track creation");
      m_tracks.at(id).input = particle->id;
    }
    return id;
  }
  std::unique_ptr<TFile> m_file;
  TTree *m_hits=nullptr;
  std::unordered_set<int> m_kept;
  std::map<int,Track> m_tracks;
  std::map<int,Vertex> m_vertices;
  std::unordered_map<const G4Track*,int> m_pending;
  std::unordered_map<int,int> m_g4;
  int m_event=-1,m_nextVertex=0,m_id=0;
  bool m_done=false;
  uint8_t m_channel=0;
  uint32_t m_collection=0;
  uint64_t m_cell=0;
  double m_deposit=0;
};
}
DECLARE_GEANT4ACTION(ColliderMLTruthCapture)
