#include "binaryninjaapi.h"
#include <string>
using namespace std;
using namespace BinaryNinja;

namespace BinaryNinja {
	static DemanglerConfig DemanglerConfigFromAPIObject(const BNDemanglerConfig* config)
	{
		DemanglerConfig result;
		if (!config)
			return result;

		result.platform = config->platform ? new CorePlatform(BNNewPlatformReference(config->platform)) : nullptr;
		result.view = config->view ? new BinaryView(BNNewViewReference(config->view)) : nullptr;
		result.simplifyTemplates = config->simplifyTemplates;
		return result;
	}

	DemanglerConfig DemanglerConfig::Default()
	{
		BNDemanglerConfig config = BNGetDefaultDemanglerConfig();
		return DemanglerConfigFromAPIObject(&config);
	}

	DemanglerConfig DemanglerConfig::ForPlatform(Platform* platform, bool simplifyTemplates)
	{
		BNDemanglerConfig config = BNGetDemanglerConfigForPlatform(platform ? platform->GetObject() : nullptr,
		    simplifyTemplates);
		return DemanglerConfigFromAPIObject(&config);
	}

	DemanglerConfig DemanglerConfig::ForBinaryView(BinaryView* view)
	{
		BNDemanglerConfig config = BNGetDemanglerConfigForBinaryView(view ? view->GetObject() : nullptr);
		return DemanglerConfigFromAPIObject(&config);
	}

	BNDemanglerConfig DemanglerConfig::GetAPIObject() const
	{
		return {
			platform ? platform->GetObject() : nullptr,
			view ? view->GetObject() : nullptr,
			simplifyTemplates,
		};
	}

	std::optional<DemanglerResult> TryDemangle(const std::string& mangledName, const DemanglerConfig& config)
	{
		BNDemanglerConfig apiConfig = config.GetAPIObject();
		BNDemanglerResult apiResult = {};
		if (!BNTryDemangle(mangledName.c_str(), &apiConfig, &apiResult))
			return std::nullopt;

		DemanglerResult result;
		result.name = QualifiedName::FromAPIObject(&apiResult.name);
		if (apiResult.type)
		{
			result.type = new Type(apiResult.type);
			apiResult.type = nullptr;
		}
		BNFreeDemanglerResult(&apiResult);
		return result;
	}

	bool DemangleGeneric(Architecture* arch, const std::string& name, Ref<Type>& outType,
		QualifiedName& outVarName, Ref<BinaryView> view, bool simplify)
	{
		BNType* apiType = nullptr;
		BNQualifiedName apiVarName;
		bool success = BNDemangleGeneric(
			arch ? arch->m_object : nullptr, name.c_str(), &apiType, &apiVarName, view ? view->m_object : nullptr,
			simplify);

		if (!success)
			return false;

		outType = apiType ? new Type(apiType) : nullptr;
		outVarName = QualifiedName::FromAPIObject(&apiVarName);
		BNFreeQualifiedName(&apiVarName);
		return true;
	}

	bool DemangleLLVM(const std::string& mangledName, QualifiedName& outVarName,
		BinaryView* view)
	{
		const bool simplify = Settings::Instance()->Get<bool>("analysis.types.templateSimplifier", view);
		return DemangleLLVM(mangledName, outVarName, simplify);
	}

	bool DemangleLLVM(const std::string& mangledName, QualifiedName& outVarName,
		const bool simplify)
	{
		char** localVarName = nullptr;
		size_t localSize = 0;
		if (!BNDemangleLLVM(mangledName.c_str(), &localVarName, &localSize, simplify))
			return false;
		for (size_t i = 0; i < localSize; i++)
		{
			outVarName.push_back(localVarName[i]);
		}
		BNFreeDemangledName(&localVarName, localSize);
		return true;
	}

	bool DemangleMS(Architecture* arch, const std::string& mangledName, Ref<Type>& outType, QualifiedName& outVarName,
	    const bool simplify)
	{
		BNType* localType = nullptr;
		char** localVarName = nullptr;
		size_t localSize = 0;
		if (!BNDemangleMS(arch ? arch->GetObject() : nullptr, mangledName.c_str(), &localType, &localVarName,
			&localSize, simplify))
			return false;
		outType = localType ? new Type(localType) : nullptr;
		for (size_t i = 0; i < localSize; i++)
		{
			outVarName.push_back(localVarName[i]);
		}
		BNFreeDemangledName(&localVarName, localSize);
		return true;
	}

	bool DemangleGNU3(Architecture* arch, const std::string& mangledName, Ref<Type>& outType, QualifiedName& outVarName,
	    const bool simplify)
	{
		BNType* localType = nullptr;
		char** localVarName = nullptr;
		size_t localSize = 0;
		if (!BNDemangleGNU3(arch ? arch->GetObject() : nullptr, mangledName.c_str(), &localType, &localVarName,
			&localSize, simplify))
			return false;
		outType = localType ? new Type(localType) : nullptr;
		outVarName.clear();
		for (size_t i = 0; i < localSize; i++)
		{
			outVarName.push_back(localVarName[i]);
		}
		BNFreeDemangledName(&localVarName, localSize);
		return true;
	}


	bool IsGNU3MangledString(const std::string& mangledName)
	{
		return BNIsGNU3MangledString(mangledName.c_str());
	}


	Demangler::Demangler(const std::string& name): m_nameForRegister(name)
	{
	}

	Demangler::Demangler(BNDemangler* demangler)
	{
		m_object = demangler;
	}

	bool Demangler::IsMangledStringCallback(void* ctxt, const char* name)
	{
		Demangler* demangler = (Demangler*)ctxt;
		return demangler->IsMangledString(name);
	}

	bool Demangler::DemangleCallback(void* ctxt, const char* name, const BNDemanglerConfig* config,
		BNDemanglerResult* result)
	{
		Demangler* demangler = (Demangler*)ctxt;

		if (!name || !result)
			return false;

		auto demangleResult = demangler->Demangle(name, DemanglerConfigFromAPIObject(config));
		if (!demangleResult)
			return false;

		if (demangleResult->type)
		{
			result->type = BNNewTypeReference(demangleResult->type->m_object);
		}
		else
		{
			result->type = nullptr;
		}
		result->name = demangleResult->name.GetAPIObject();

		return true;
	}

	void Demangler::FreeResultCallback(void* ctxt, BNDemanglerResult* result)
	{
		BNFreeDemanglerResult(result);
	}

	void Demangler::Register(Demangler* demangler)
	{
		BNDemanglerCallbacks cb;
		cb.context = (void*)demangler;
		cb.isMangledString = IsMangledStringCallback;
		cb.demangle = DemangleCallback;
		cb.freeResult = FreeResultCallback;
		demangler->m_object = BNRegisterDemangler(demangler->m_nameForRegister.c_str(), &cb);
	}

	std::vector<Ref<Demangler>> Demangler::GetList()
	{
		size_t count;
		BNDemangler** list = BNGetDemanglerList(&count);
		vector<Ref<Demangler>> result;
		result.reserve(count);
		for (size_t i = 0; i < count; i++)
			result.push_back(new CoreDemangler(list[i]));
		BNFreeDemanglerList(list);
		return result;
	}

	Ref<Demangler> Demangler::GetByName(const std::string& name)
	{
		BNDemangler* result = BNGetDemanglerByName(name.c_str());
		if (!result)
			return nullptr;
		return new CoreDemangler(result);
	}

	void Demangler::Promote(Ref<Demangler> demangler)
	{
		BNPromoteDemangler(demangler->m_object);
	}

	std::string Demangler::GetName() const
	{
		char* name = BNGetDemanglerName(m_object);
		std::string value = name;
		BNFreeString(name);
		return value;
	}

	CoreDemangler::CoreDemangler(BNDemangler* demangler): Demangler(demangler)
	{
	}

	bool CoreDemangler::IsMangledString(const std::string& name)
	{
		return BNIsDemanglerMangledName(m_object, name.c_str());
	}

	std::optional<Demangler::Result> CoreDemangler::Demangle(const std::string& name, const Config& config)
	{
		BNDemanglerConfig apiConfig = config.GetAPIObject();
		BNDemanglerResult apiResult = {};
		bool success = BNDemanglerTryDemangle(m_object, name.c_str(), &apiConfig, &apiResult);

		if (!success)
			return std::nullopt;

		Result result;
		result.name = QualifiedName::FromAPIObject(&apiResult.name);
		if (apiResult.type)
		{
			result.type = new Type(apiResult.type);
			apiResult.type = nullptr;
		}
		BNFreeDemanglerResult(&apiResult);
		return result;
	}
}  // namespace BinaryNinja
